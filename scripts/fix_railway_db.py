"""
Fix Railway Database Column Sizes
Run this ONCE on Railway to fix existing column sizes
"""
import os
import sys

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from models import db

def fix_column_sizes():
    """Fix column sizes for existing tables."""
    app = create_app()
    
    with app.app_context():
        print("Starting column size fixes...")
        
        try:
            # Check if table exists first
            check_sql = """
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_name = 'cv_candidates'
            );
            """
            result = db.session.execute(db.text(check_sql))
            table_exists = result.scalar()
            
            if not table_exists:
                print("⚠️  Table 'cv_candidates' doesn't exist yet.")
                print("Running db.create_all() first...")
                db.create_all()
                print("✅ Tables created!")
                return
            
            # Check current column size
            check_column_sql = """
            SELECT column_name, character_maximum_length 
            FROM information_schema.columns 
            WHERE table_name = 'cv_candidates' 
            AND column_name = 'source_file_id';
            """
            result = db.session.execute(db.text(check_column_sql))
            row = result.fetchone()
            
            if row:
                current_length = row[1]
                print(f"Current source_file_id length: {current_length}")
                
                if current_length == 500:
                    print("✅ Column is already the correct size (500)!")
                    return
                
                # Alter the column
                print("Altering source_file_id column to VARCHAR(500)...")
                alter_sql = """
                ALTER TABLE cv_candidates 
                ALTER COLUMN source_file_id TYPE VARCHAR(500);
                """
                db.session.execute(db.text(alter_sql))
                db.session.commit()
                
                # Verify the change
                result = db.session.execute(db.text(check_column_sql))
                row = result.fetchone()
                new_length = row[1]
                
                print(f"✅ Column altered successfully! New length: {new_length}")
            else:
                print("⚠️  Column 'source_file_id' not found. Creating table...")
                db.create_all()
                print("✅ Tables created!")
            
        except Exception as e:
            print(f"❌ Error during column fix: {e}")
            db.session.rollback()
            raise

if __name__ == '__main__':
    fix_column_sizes()
