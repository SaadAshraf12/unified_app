"""
Database Models for Unified AI Agents Application
"""
from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from cryptography.fernet import Fernet
import os
import json

db = SQLAlchemy()


def get_cipher():
    """Get Fernet cipher for encryption/decryption."""
    key = os.getenv('ENCRYPTION_KEY', '')
    if not key:
        # Generate a key for development (not secure for production)
        key = Fernet.generate_key().decode()
    return Fernet(key.encode() if isinstance(key, str) else key)


def encrypt_value(value):
    """Encrypt a string value."""
    if not value:
        return None
    cipher = get_cipher()
    return cipher.encrypt(value.encode()).decode()


def decrypt_value(encrypted_value):
    """Decrypt an encrypted string value."""
    if not encrypted_value:
        return None
    try:
        cipher = get_cipher()
        return cipher.decrypt(encrypted_value.encode()).decode()
    except Exception:
        return None


class User(UserMixin, db.Model):
    """User model for authentication."""
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    name = db.Column(db.String(100), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_login = db.Column(db.DateTime, nullable=True)
    
    # Relationships
    settings = db.relationship('UserSettings', backref='user', uselist=False, cascade='all, delete-orphan')
    email_config = db.relationship('EmailAgentConfig', backref='user', uselist=False, cascade='all, delete-orphan')
    meeting_config = db.relationship('MeetingAgentConfig', backref='user', uselist=False, cascade='all, delete-orphan')
    bot_config = db.relationship('BotConfig', backref='user', uselist=False, cascade='all, delete-orphan')
    processed_emails = db.relationship('ProcessedEmail', backref='user', lazy='dynamic', cascade='all, delete-orphan')
    processed_meetings = db.relationship('ProcessedMeeting', backref='user', lazy='dynamic', cascade='all, delete-orphan')
    
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)
    
    def __repr__(self):
        return f'<User {self.email}>'


class UserSettings(db.Model):
    """User API credentials and settings."""
    __tablename__ = 'user_settings'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, unique=True)
    
    # Microsoft Azure credentials (encrypted)
    azure_client_id = db.Column(db.String(256), nullable=True)
    azure_tenant_id = db.Column(db.String(256), nullable=True)
    _ms_access_token = db.Column('ms_access_token', db.Text, nullable=True)
    _ms_refresh_token = db.Column('ms_refresh_token', db.Text, nullable=True)
    ms_token_expires_at = db.Column(db.DateTime, nullable=True)
    
    # ClickUp API key (encrypted)
    _clickup_api_key = db.Column('clickup_api_key', db.String(512), nullable=True)
    
    # OpenAI API key (encrypted, optional - uses app default if not set)
    _openai_api_key = db.Column('openai_api_key', db.String(512), nullable=True)
    
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    @property
    def clickup_api_key(self):
        return decrypt_value(self._clickup_api_key)
    
    @clickup_api_key.setter
    def clickup_api_key(self, value):
        self._clickup_api_key = encrypt_value(value)
    
    @property
    def openai_api_key(self):
        return decrypt_value(self._openai_api_key)
    
    @openai_api_key.setter
    def openai_api_key(self, value):
        self._openai_api_key = encrypt_value(value)
    
    @property
    def ms_access_token(self):
        return decrypt_value(self._ms_access_token)
    
    @ms_access_token.setter
    def ms_access_token(self, value):
        self._ms_access_token = encrypt_value(value)
    
    @property
    def ms_refresh_token(self):
        return decrypt_value(self._ms_refresh_token)
    
    @ms_refresh_token.setter
    def ms_refresh_token(self, value):
        self._ms_refresh_token = encrypt_value(value)


class EmailAgentConfig(db.Model):
    """Configuration for Email Agent per user."""
    __tablename__ = 'email_agent_configs'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, unique=True)
    
    # ClickUp settings
    clickup_list_id = db.Column(db.String(50), nullable=True)
    
    # Filters (stored as JSON)
    _allowed_senders = db.Column('allowed_senders', db.Text, default='[]')
    _allowed_assignees = db.Column('allowed_assignees', db.Text, default='[]')
    _sensitive_keywords = db.Column('sensitive_keywords', db.Text, default='[]')
    _ignore_subject_prefixes = db.Column('ignore_subject_prefixes', db.Text, 
                                         default='["Automatic reply:", "Accepted:", "Declined:", "Tentative:", "Canceled:"]')
    
    # Agent settings
    is_enabled = db.Column(db.Boolean, default=True)
    auto_run_interval = db.Column(db.Integer, default=0)  # 0 = manual only, otherwise minutes
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    @property
    def allowed_senders(self):
        return json.loads(self._allowed_senders or '[]')
    
    @allowed_senders.setter
    def allowed_senders(self, value):
        self._allowed_senders = json.dumps(value if isinstance(value, list) else [])
    
    @property
    def allowed_assignees(self):
        return json.loads(self._allowed_assignees or '[]')
    
    @allowed_assignees.setter
    def allowed_assignees(self, value):
        self._allowed_assignees = json.dumps(value if isinstance(value, list) else [])
    
    @property
    def sensitive_keywords(self):
        return json.loads(self._sensitive_keywords or '[]')
    
    @sensitive_keywords.setter
    def sensitive_keywords(self, value):
        self._sensitive_keywords = json.dumps(value if isinstance(value, list) else [])
    
    @property
    def ignore_subject_prefixes(self):
        return json.loads(self._ignore_subject_prefixes or '[]')
    
    @ignore_subject_prefixes.setter
    def ignore_subject_prefixes(self, value):
        self._ignore_subject_prefixes = json.dumps(value if isinstance(value, list) else [])


class MeetingAgentConfig(db.Model):
    """Configuration for Meeting Agent per user."""
    __tablename__ = 'meeting_agent_configs'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, unique=True)
    
    # ClickUp settings
    clickup_list_id = db.Column(db.String(50), nullable=True)
    target_space_id = db.Column(db.String(50), nullable=True)
    target_doc_name = db.Column(db.String(200), default='Daily Standup Summary By AI')
    
    # Email alerts
    helpdesk_email = db.Column(db.String(120), nullable=True)
    
    # Meeting filters (stored as JSON)
    _meeting_name_filters = db.Column('meeting_name_filters', db.Text, default='[]')
    _standup_meeting_keywords = db.Column('standup_meeting_keywords', db.Text, 
                                          default='["Daily Standup", "Stand-up", "Standup"]')
    _excluded_meeting_names = db.Column('excluded_meeting_names', db.Text, default='[]')
    
    # Agent settings
    is_enabled = db.Column(db.Boolean, default=True)
    auto_run_interval = db.Column(db.Integer, default=0)
    scan_days_back = db.Column(db.Integer, default=2)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    @property
    def meeting_name_filters(self):
        return json.loads(self._meeting_name_filters or '[]')
    
    @meeting_name_filters.setter
    def meeting_name_filters(self, value):
        self._meeting_name_filters = json.dumps(value if isinstance(value, list) else [])
    
    @property
    def standup_meeting_keywords(self):
        return json.loads(self._standup_meeting_keywords or '[]')
    
    @standup_meeting_keywords.setter
    def standup_meeting_keywords(self, value):
        self._standup_meeting_keywords = json.dumps(value if isinstance(value, list) else [])
    
    @property
    def excluded_meeting_names(self):
        return json.loads(self._excluded_meeting_names or '[]')
    
    @excluded_meeting_names.setter
    def excluded_meeting_names(self, value):
        self._excluded_meeting_names = json.dumps(value if isinstance(value, list) else [])


class BotConfig(db.Model):
    """Configuration for Meeting Bot per user."""
    __tablename__ = 'bot_configs'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, unique=True)
    
    # Bot personality
    bot_name = db.Column(db.String(50), default='Brian')
    _wake_words = db.Column('wake_words', db.Text, default='["hello Brian", "hey Brian", "Brian"]')
    _dismissal_phrases = db.Column('dismissal_phrases', db.Text, 
                                   default='["that\'s all", "thanks Brian", "goodbye", "bye"]')
    
    # ClickUp context
    clickup_space_name = db.Column(db.String(100), default='AI Context')
    clickup_summary_doc_name = db.Column(db.String(200), default='Daily Standup Summary By AI')
    
    # Settings
    is_enabled = db.Column(db.Boolean, default=True)
    timeout_seconds = db.Column(db.Integer, default=50)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    @property
    def wake_words(self):
        return json.loads(self._wake_words or '[]')
    
    @wake_words.setter
    def wake_words(self, value):
        self._wake_words = json.dumps(value if isinstance(value, list) else [])
    
    @property
    def dismissal_phrases(self):
        return json.loads(self._dismissal_phrases or '[]')
    
    @dismissal_phrases.setter
    def dismissal_phrases(self, value):
        self._dismissal_phrases = json.dumps(value if isinstance(value, list) else [])


class ProcessedEmail(db.Model):
    """Track processed emails per user."""
    __tablename__ = 'processed_emails'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    email_id = db.Column(db.String(200), nullable=False)
    subject = db.Column(db.String(500), nullable=True)
    sender = db.Column(db.String(200), nullable=True)
    tasks_created = db.Column(db.Integer, default=0)
    processed_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    __table_args__ = (
        db.UniqueConstraint('user_id', 'email_id', name='unique_user_email'),
    )


class ProcessedMeeting(db.Model):
    """Track processed meetings/transcripts per user."""
    __tablename__ = 'processed_meetings'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    transcript_id = db.Column(db.String(200), nullable=False)
    meeting_subject = db.Column(db.String(500), nullable=True)
    tasks_created = db.Column(db.Integer, default=0)
    standup_summary_created = db.Column(db.Boolean, default=False)
    processed_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    __table_args__ = (
        db.UniqueConstraint('user_id', 'transcript_id', name='unique_user_transcript'),
    )


class ActivityLog(db.Model):
    """Activity logs for dashboard."""
    __tablename__ = 'activity_logs'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    agent_type = db.Column(db.String(20), nullable=False)  # 'email', 'meeting', 'bot'
    action = db.Column(db.String(50), nullable=False)
    message = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(20), default='success')  # 'success', 'error', 'warning'
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    user = db.relationship('User', backref=db.backref('activity_logs', lazy='dynamic'))
