"""
ATS Agent Routes - Flask endpoints for dashboard, config, and scanning
"""
import os
from datetime import datetime
from flask import render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename

from . import ats_bp
from models import db, ATSAgentConfig, CVCandidate, ATSScanHistory, ActivityLog
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
    """AJAX endpoint to trigger CV scan (runs in background via Celery)."""
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
        
        # Check if MS token exists
        if not settings.ms_access_token:
            return jsonify({'success': False, 'error': 'Microsoft account not connected'})
        
        # Trigger background Celery task instead of running synchronously
        from agents.ats_agent.tasks import process_ats_scan
        process_ats_scan.delay(current_user.id)  # Run in background via Celery
        
        # Log activity
        log = ActivityLog(
            user_id=current_user.id,
            agent_type='ats',
            action='scan_triggered',
            message='ATS scan started (running in background)',
            status='success'
        )
        db.session.add(log)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Scan started! Refresh the page in a few moments to see results.',
            'info': 'The scan is running in the background and may take 1-2 minutes depending on the number of CVs found.'
        })
        
    except Exception as e:
        print(f"Error triggering ATS scan: {e}")
        import traceback
        traceback.print_exc()
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
