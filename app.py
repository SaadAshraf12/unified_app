"""
Unified AI Agents - Flask Application
"""
import os
from flask import Flask, redirect, url_for
from flask_login import LoginManager
from models import db, User
from config import config

login_manager = LoginManager()


def create_app(config_name=None):
    """Application factory."""
    if config_name is None:
        config_name = os.getenv('FLASK_ENV', 'development')
    
    app = Flask(__name__)
    app.config.from_object(config[config_name])
    
    # Initialize extensions
    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'
    login_manager.login_message = 'Please log in to access this page.'
    login_manager.login_message_category = 'info'
    
    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))
    
    # Register blueprints
    from auth.routes import auth_bp
    from agents.email_agent.routes import email_bp
    from agents.meeting_agent.routes import meeting_bp
    
    app.register_blueprint(auth_bp, url_prefix='/auth')
    app.register_blueprint(email_bp, url_prefix='/email')
    app.register_blueprint(meeting_bp, url_prefix='/meeting')
    
    # Main routes
    @app.route('/')
    def index():
        return redirect(url_for('auth.dashboard'))
    
    # Create database tables
    with app.app_context():
        db.create_all()
    
    return app


# Create app instance for running directly
app = create_app()


if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5000, debug=True)
