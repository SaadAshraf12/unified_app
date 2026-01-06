"""
ATS Agent Routes - Flask endpoints for dashboard, config, and scanning
"""
import os
from datetime import datetime
from flask import render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename

from . import ats_bp
from models import db, ATSAgentConfig, CVCandidate, ATSScanHistory
from .parser import extract_text_from_cv, parse_cv_basic_info
from .filters import apply_hard_filters
from .scorer import score_cv_with_openai, calculate_weighted_score
from .scanner import scan_outlook_folder, scan_sharepoint_library, download_file, save_base64_file


UPLOAD_FOLDER = 'static/uploads/cvs'
ALLOWED_EXTENSIONS = {' pdf', 'docx', 'doc'}


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


@ats_bp.route('/dashboard')
@login_required
def dashboard():
    """ATS Agent Dashboard."""
    # Get or create config
    config = ATSAgentConfig.query.filter_by(user_id=current_user.id).first()
    if not config:
        config = ATSAgentConfig(user_id=current_user.id)
        db.session.add(config)
        db.session.commit()
    
    # Get statistics
    total_cvs = CVCandidate.query.filter_by(user_id=current_user.id).count()
    scored_cvs = CVCandidate.query.filter_by(user_id=current_user.id, status='scored').count()
    filtered_cvs = CVCandidate.query.filter_by(user_id=current_user.id, status='filtered_out').count()
    
    # Get average score
    scored_candidates = CVCandidate.query.filter_by(user_id=current_user.id, status='scored').all()
    avg_score = 0
    if scored_candidates:
        avg_score = sum(float(c.final_weighted_score or 0) for c in scored_candidates) / len(scored_candidates)
    
    # Get top candidates
    top_candidates = CVCandidate.query.filter_by(user_id=current_user.id, status='scored')\
        .order_by(CVCandidate.final_weighted_score.desc())\
        .limit(config.top_n_candidates).all()
    
    # Get recent scans
    recent_scans = ATSScanHistory.query.filter_by(user_id=current_user.id)\
        .order_by(ATSScanHistory.scan_started_at.desc())\
        .limit(5).all()
    
    return render_template('ats/dashboard.html',
                         config=config,
                         total_cvs=total_cvs,
                         scored_cvs=scored_cvs,
                         filtered_cvs=filtered_cvs,
                         avg_score=round(avg_score, 1),
                         top_candidates=top_candidates,
                         recent_scans=recent_scans)


@ats_bp.route('/config', methods=['GET', 'POST'])
@login_required
def config():
    """ATS Agent Configuration."""
    ats_config = ATSAgentConfig.query.filter_by(user_id=current_user.id).first()
    if not ats_config:
        ats_config = ATSAgentConfig(user_id=current_user.id)
        db.session.add(ats_config)
        db.session.commit()
    
    if request.method == 'POST':
        # Job Details
        ats_config.job_title = request.form.get('job_title')
        ats_config.job_description = request.form.get('job_description')
        required_skills = request.form.get('required_skills', '').split(',')
        ats_config.required_skills = [s.strip() for s in required_skills if s.strip()]
        
        # Filters
        allowed_locs = request.form.get('allowed_locations', '').split(',')
        ats_config.allowed_locations = [l.strip() for l in allowed_locs if l.strip()]
        ats_config.min_experience = int(request.form.get('min_experience', 0))
        ats_config.max_experience = int(request.form.get('max_experience', 99))
        ats_config.min_education_level = request.form.get('min_education_level')
        must_have = request.form.get('must_have_skills', '').split(',')
        ats_config.must_have_skills = [s.strip() for s in must_have if s.strip()]
        
        # Scoring Weights
        ats_config.weight_skills = float(request.form.get('weight_skills', 0.4))
        ats_config.weight_title = float(request.form.get('weight_title', 0.2))
        ats_config.weight_experience = float(request.form.get('weight_experience', 0.2))
        ats_config.weight_education = float(request.form.get('weight_education', 0.1))
        ats_config.weight_keywords = float(request.form.get('weight_keywords', 0.1))
        
        # CV Sources
        ats_config.onedrive_enabled = 'onedrive_enabled' in request.form
        ats_config.onedrive_folder_path = request.form.get('onedrive_folder_path', 'CVs')
        ats_config.email_folder_enabled = 'email_folder_enabled' in request.form
        ats_config.email_folder_name = request.form.get('email_folder_name', 'Recruitment')
        ats_config.email_inbox_enabled = 'email_inbox_enabled' in request.form
        ats_config.sharepoint_enabled = 'sharepoint_enabled' in request.form
        ats_config.sharepoint_site_url = request.form.get('sharepoint_site_url')
        ats_config.sharepoint_library = request.form.get('sharepoint_library')
        
        # Output Config
        ats_config.top_n_candidates = int(request.form.get('top_n_candidates', 10))
        ats_config.min_threshold_score = int(request.form.get('min_threshold_score', 60))
        
        ats_config.is_enabled = 'is_enabled' in request.form
        
        db.session.commit()
        flash('ATS configuration saved successfully!', 'success')
        return redirect(url_for('ats.dashboard'))
    
    return render_template('ats/config.html', config=ats_config)


@ats_bp.route('/run', methods=['POST'])
@login_required
def run():
    """Trigger CV scanning and processing."""
    flash('Scan started! Processing CVs in background...', 'info')
    return redirect(url_for('ats.dashboard'))


@ats_bp.route('/run_ajax', methods=['POST'])
@login_required
def run_ajax():
    """AJAX endpoint to run CV scan."""
    try:
        # Get config
        config = ATSAgentConfig.query.filter_by(user_id=current_user.id).first()
        if not config or not config.is_enabled:
            return jsonify({'success': False, 'error': 'ATS agent not configured or disabled'})
        
        # Get OpenAI API key
        from models import UserSettings
        settings = UserSettings.query.filter_by(user_id=current_user.id).first()
        if not settings or not settings.openai_api_key:
            return jsonify({'success': False, 'error': 'OpenAI API key not configured'})
        
        # Create scan history record
        scan = ATSScanHistory(user_id=current_user.id, status='running')
        db.session.add(scan)
        db.session.commit()
        
        # This is a simplified version - in production, use Celery for background processing
        cv_files = []
        
        print(f"DEBUG: Starting CV scan...")
        print(f"DEBUG: OneDrive enabled: {config.onedrive_enabled}")
        print(f"DEBUG: Email inbox enabled: {config.email_inbox_enabled}")
        print(f"DEBUG: Email folder enabled: {config.email_folder_enabled}")
        print(f"DEBUG: SharePoint enabled: {config.sharepoint_enabled}")
        print(f"DEBUG: MS Access token present: {bool(settings.ms_access_token)}")
        
        # Scan OneDrive
        if config.onedrive_enabled and settings.ms_access_token:
            print(f"DEBUG: Scanning OneDrive folder: {config.onedrive_folder_path}")
            from .scanner import scan_onedrive_folder
            onedrive_cvs = scan_onedrive_folder(settings.ms_access_token, config.onedrive_folder_path)
            print(f"DEBUG: Found {len(onedrive_cvs)} CVs from OneDrive")
            cv_files.extend(onedrive_cvs)
        
        # Scan Email Inbox
        if config.email_inbox_enabled and settings.ms_access_token:
            print(f"DEBUG: Scanning email inbox...")
            from .scanner import scan_email_attachments
            inbox_cvs = scan_email_attachments(settings.ms_access_token, folder_name=None)
            print(f"DEBUG: Found {len(inbox_cvs)} CVs from inbox")
            cv_files.extend(inbox_cvs)
        
        # Scan Email Folder
        if config.email_folder_enabled and settings.ms_access_token:
            print(f"DEBUG: Scanning email folder: {config.email_folder_name}")
            from .scanner import scan_email_attachments
            folder_cvs = scan_email_attachments(settings.ms_access_token, config.email_folder_name)
            print(f"DEBUG: Found {len(folder_cvs)} CVs from folder")
            cv_files.extend(folder_cvs)
        
        # Scan SharePoint
        if config.sharepoint_enabled and config.sharepoint_site_url and settings.ms_access_token:
            print(f"DEBUG: Scanning SharePoint...")
            sp_cvs = scan_sharepoint_library(
                settings.ms_access_token,
                config.sharepoint_site_url,
                config.sharepoint_library
            )
            print(f"DEBUG: Found {len(sp_cvs)} CVs from SharePoint")
            cv_files.extend(sp_cvs)
        
        print(f"DEBUG: Total CVs found: {len(cv_files)}")
        
        scan.total_cvs_found = len(cv_files)
        
        processed = 0
        scored = 0
        filtered = 0
        
        # Process each CV
        for cv_file in cv_files:
            # Skip if already processed
            existing = CVCandidate.query.filter_by(
                user_id=current_user.id,
                source_file_id=cv_file['source_id']
            ).first()
            if existing:
                continue
            
            # Download/save file
            filename = secure_filename(cv_file['filename'])
            filepath = os.path.join(UPLOAD_FOLDER, f"{current_user.id}_{datetime.now().timestamp()}_{filename}")
            os.makedirs(os.path.dirname(filepath), exist_ok=True)
            
            if cv_file.get('download_url'):
                download_file(cv_file['download_url'], filepath, settings.ms_access_token)
            elif cv_file.get('content'):
                save_base64_file(cv_file['content'], filepath)
            
            # Parse CV
            cv_text = extract_text_from_cv(filepath)
            if not cv_text:
                continue
            
            basic_info = parse_cv_basic_info(cv_text)
            
            # Create candidate record
            candidate = CVCandidate(
                user_id=current_user.id,
                cv_text=cv_text,
                cv_file_path=filepath,
                cv_source=cv_file['source'],
                source_file_id=cv_file['source_id'],
                source_file_name=cv_file['filename'],
                full_name=basic_info.get('name'),
                email=basic_info.get('email'),
                phone=basic_info.get('phone'),
                linkedin_url=basic_info.get('linkedin_url')
            )
            
            # Apply hard filters
            filter_config = {
                'allowed_locations': config.allowed_locations,
                'min_experience': config.min_experience,
                'max_experience': config.max_experience,
                'must_have_skills': config.must_have_skills
            }
            
            passed, reasons = apply_hard_filters({'cv_text': cv_text}, filter_config)
            
            if not passed:
                candidate.status = 'filtered_out'
                filtered += 1
            else:
                # Score with OpenAI
                job_config = {
                    'job_title': config.job_title,
                    'job_description': config.job_description,
                    'required_skills': config.required_skills
                }
                
                score_result = score_cv_with_openai(
                    {'cv_text': cv_text},
                    job_config,
                    settings.openai_api_key
                )
                
                if score_result:
                    # Update candidate with scores
                    candidate.skills_score = score_result.get('skills_score')
                    candidate.skills_reasoning = score_result.get('skills_reasoning')
                    candidate.title_score = score_result.get('title_score')
                    candidate.title_reasoning = score_result.get('title_reasoning')
                    candidate.experience_score = score_result.get('experience_score')
                    candidate.experience_reasoning = score_result.get('experience_reasoning')
                    candidate.education_score = score_result.get('education_score')
                    candidate.education_reasoning = score_result.get('education_reasoning')
                    candidate.keywords_score = score_result.get('keywords_score')
                    candidate.keywords_reasoning = score_result.get('keywords_reasoning')
                    candidate.overall_assessment = score_result.get('overall_assessment')
                    candidate.red_flags = score_result.get('red_flags', [])
                    
                    # Calculate weighted score
                    weights = {
                        'weight_skills': config.weight_skills,
                        'weight_title': config.weight_title,
                        'weight_experience': config.weight_experience,
                        'weight_education': config.weight_education,
                        'weight_keywords': config.weight_keywords
                    }
                    candidate.final_weighted_score = calculate_weighted_score(score_result, weights)
                    
                    # Update extracted data
                    candidate.years_of_experience = score_result.get('years_of_experience')
                    candidate.location = score_result.get('location')
                    candidate.current_job_title = score_result.get('current_title')
                    candidate.skills = score_result.get('extracted_skills', [])
                    
                    candidate.status = 'scored'
                    candidate.processed_at = datetime.utcnow()
                    scored += 1
            
            db.session.add(candidate)
            processed += 1
        
        # Update scan history
        scan.cvs_processed = processed
        scan.cvs_scored = scored
        scan.cvs_filtered_out = filtered
        scan.status = 'completed'
        scan.scan_completed_at = datetime.utcnow()
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'cvs_found': scan.total_cvs_found,
            'processed': processed,
            'scored': scored,
            'filtered': filtered
        })
        
    except Exception as e:
        scan.status = 'failed'
        scan.error_message = str(e)
        db.session.commit()
        return jsonify({'success': False, 'error': str(e)})


@ats_bp.route('/results')
@login_required
def results():
    """View all candidates."""
    candidates = CVCandidate.query.filter_by(user_id=current_user.id, status='scored')\
        .order_by(CVCandidate.final_weighted_score.desc()).all()
    
    return render_template('ats/results.html', candidates=candidates)


@ats_bp.route('/candidate/<int:candidate_id>')
@login_required
def candidate_detail(candidate_id):
    """View detailed candidate profile."""
    candidate = CVCandidate.query.filter_by(id=candidate_id, user_id=current_user.id).first_or_404()
    return render_template('ats/candidate.html', candidate=candidate)


@ats_bp.route('/history')
@login_required
def history():
    """View scan history."""
    scans = ATSScanHistory.query.filter_by(user_id=current_user.id)\
        .order_by(ATSScanHistory.scan_started_at.desc()).all()
    
    return render_template('ats/history.html', scans=scans)
