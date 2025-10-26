from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, send_file
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import os
from datetime import datetime
import logging
import requests
import re
# Remove NLTK imports
# import nltk
# from nltk import word_tokenize, pos_tag
from sqlalchemy.orm import joinedload
from functools import wraps

# Add a simple stopword list for English
STOPWORDS = set([
    'the', 'and', 'for', 'are', 'but', 'not', 'you', 'all', 'any', 'can', 'had', 'her', 'was', 'one', 'our', 'out', 'day', 'get', 'has', 'him', 'his', 'how', 'man', 'new', 'now', 'old', 'see', 'two', 'way', 'who', 'boy', 'did', 'its', 'let', 'put', 'say', 'she', 'too', 'use', 'a', 'an', 'in', 'on', 'at', 'to', 'of', 'is', 'it', 'as', 'by', 'be', 'or', 'if', 'with', 'from', 'this', 'that', 'these', 'those', 'their', 'there', 'which', 'so', 'such', 'then', 'than', 'also', 'have', 'will', 'would', 'should', 'could', 'may', 'might', 'must', 'do', 'does', 'did', 'been', 'were', 'am', 'i', 'we', 'he', 'she', 'they', 'them', 'my', 'your', 'his', 'her', 'its', 'our', 'their', 'me', 'him', 'us', 'theirs', 'ours', 'yours', 'mine', 'about', 'above', 'after', 'again', 'against', 'below', 'between', 'down', 'during', 'each', 'few', 'more', 'most', 'other', 'some', 'such', 'no', 'nor', 'only', 'own', 'same', 'too', 'very', 's', 't', 'can', 'will', 'just', 'don', 'should', 'now'
])

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Initialize Affinda API configuration
API_KEY = "aff_aca7e654b91c3fe9ed00355e278d62baeeaefd4d"
BASE_URL = "https://api.affinda.com/v1/resumes"
app = Flask(__name__)
app.config['SECRET_KEY'] = os.urandom(24)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///job_portal.db'
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size

if not os.path.exists(app.config['UPLOAD_FOLDER']):
    os.makedirs(app.config['UPLOAD_FOLDER'])

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(128))
    is_recruiter = db.Column(db.Boolean, default=False)
    is_admin = db.Column(db.Boolean, default=False)  # NEW FIELD
    resume_path = db.Column(db.String(200))
    skills = db.Column(db.String(500))
    experience = db.Column(db.String(500))

class Job(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=False)
    requirements = db.Column(db.Text, nullable=False)
    skills = db.Column(db.String(500))
    posted_by = db.Column(db.Integer, db.ForeignKey('user.id'))
    posted_by_user = db.relationship('User', backref='jobs_posted', foreign_keys=[posted_by])
    posted_date = db.Column(db.DateTime, default=datetime.utcnow)
    is_active = db.Column(db.Boolean, default=True)
    applications = db.relationship('JobApplication', backref='job', lazy=True)

class JobApplication(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    job_id = db.Column(db.Integer, db.ForeignKey('job.id'))
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    match_score = db.Column(db.Float)
    applied_date = db.Column(db.DateTime, default=datetime.utcnow)
    resume_parse_time = db.Column(db.Float)  # Time taken to parse resume
    match_calc_time = db.Column(db.Float)    # Time taken to calculate match score
    user = db.relationship('User', backref='applications', lazy=True)

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not getattr(current_user, 'is_admin', False):
            flash('Admin access required.', 'danger')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

@app.route('/stats')
@login_required
def stats():
    if not current_user.is_recruiter:
        return redirect(url_for('dashboard'))
    
    # Calculate metrics
    total_jobs = Job.query.count()
    total_applications = JobApplication.query.count()
    avg_match_score = db.session.query(db.func.avg(JobApplication.match_score)).scalar() or 0
    avg_parse_time = db.session.query(db.func.avg(JobApplication.resume_parse_time)).scalar() or 0
    avg_match_time = db.session.query(db.func.avg(JobApplication.match_calc_time)).scalar() or 0
    
    return render_template('stats.html', 
                         total_jobs=total_jobs,
                         total_applications=total_applications,
                         avg_match_score=avg_match_score,
                         avg_parse_time=avg_parse_time,
                         avg_match_time=avg_match_time)

@login_manager.user_loader
def load_user(id):
    return User.query.get(int(id))

@app.route('/')
def index():
    jobs = Job.query.filter_by(is_active=True).all()
    return render_template('index.html', jobs=jobs)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']
        is_recruiter = request.form.get('is_recruiter')
        
        if User.query.filter_by(email=email).first():
            flash('Email already registered', 'error')
            return redirect(url_for('register'))
            
        user = User(
            username=username,
            email=email,
            password_hash=generate_password_hash(password),
            is_recruiter=bool(is_recruiter)
        )
        db.session.add(user)
        db.session.commit()
        flash('Registration successful!', 'success')
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = User.query.filter_by(email=request.form['email']).first()
        if user and check_password_hash(user.password_hash, request.form['password']):
            login_user(user)
            # Ensure is_admin is set on user object
            if not hasattr(user, 'is_admin'):
                user.is_admin = False
            if user.is_admin:
                return redirect(url_for('admin_recruiter_dashboard'))
            else:
                return redirect(url_for('dashboard'))
        flash('Invalid email or password', 'error')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))

@app.route('/upload_resume', methods=['POST'])
@login_required
def upload_resume():
    if 'resume' not in request.files:
        flash('No file part', 'error')
        return redirect(request.referrer)
    
    file = request.files['resume']
    if not file or not file.filename:
        flash('No selected file', 'error')
        return redirect(request.referrer)
    
    filename = secure_filename(str(file.filename))
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(filepath)
        
        # Parse resume using direct API call
    try:
        with open(filepath, 'rb') as f:
            files = {
                'file': (filename, f, 'application/pdf')
            }
            
            headers = {
                'Authorization': f'Bearer {API_KEY}'
            }
            
            response = requests.post(
                BASE_URL,
                headers=headers,
                files=files
            )
            
            if response.status_code == 200:
                resume_data = response.json().get('data', {})
                # Extract skills as comma-separated names
                skills = ', '.join([s['name'] for s in resume_data.get('skills', []) if 'name' in s])
                # Extract experience from WorkExperience sections or profession
                sections = resume_data.get('sections', [])
                experience = ' '.join([s['text'] for s in sections if s.get('sectionType') == 'WorkExperience'])
                if not experience:
                    experience = resume_data.get('profession', '')
                current_user.resume_path = filepath
                current_user.skills = skills
                current_user.experience = experience
                db.session.commit()
                
                flash('Resume uploaded and parsed successfully!', 'success')
                return redirect(url_for('dashboard'))
            else:
                logger.error(f'Resume parsing error: {response.status_code} - {response.text}')
                flash(f'Failed to parse resume: {response.status_code} - {response.text}', 'error')
                return redirect(request.referrer)
    except Exception as e:
        logger.error(f'Resume parsing error: {str(e)}')
        flash(f'Error during resume parsing: {str(e)}', 'error')
        return redirect(request.referrer)

@app.route('/download_resume')
@login_required
def download_resume():
    if not current_user.resume_path:
        flash('No resume uploaded', 'error')
        return redirect(url_for('dashboard'))
    
    return send_file(current_user.resume_path, as_attachment=True)

@app.route('/download_resume/<int:user_id>')
@login_required
def download_applicant_resume(user_id):
    if not current_user.is_recruiter:
        flash('You are not authorized to download resumes.', 'danger')
        return redirect(url_for('dashboard'))
    user = User.query.get_or_404(user_id)
    if not user.resume_path or not os.path.exists(user.resume_path):
        flash('Resume file not found.', 'danger')
        return redirect(request.referrer or url_for('dashboard'))
    return send_file(user.resume_path, as_attachment=True)

@app.route('/post_job', methods=['GET', 'POST'])
@login_required
def post_job():
    if not current_user.is_recruiter:
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        title = request.form['title']
        description = request.form['description']
        requirements = request.form['requirements']
        skills = request.form['skills']
        job = Job(
            title=title,
            description=description,
            requirements=requirements,
            skills=skills,
            posted_by=current_user.id
        )
        db.session.add(job)
        db.session.commit()
        flash('Job posted successfully!', 'success')
        return redirect(url_for('dashboard'))
    
    return render_template('post_job.html')

@app.route('/job/<int:job_id>')
@login_required
def job_detail(job_id):
    job = Job.query.get_or_404(job_id)
    
    # Check if user has applied
    application = JobApplication.query.filter_by(
        user_id=current_user.id,
        job_id=job_id
    ).first()
    applied = application is not None
    
    # Calculate match score if user has a resume
    match_score = 0
    skills_matched = []
    
    if current_user.resume_path:
        # Get job description and user resume data
        job_text = (job.description or '') + ' ' + (job.requirements or '')
        resume_text = (current_user.skills or '') + ' ' + (current_user.experience or '')

        # Extract noun-like words (words longer than 2 chars, not stopwords)
        job_words = set([w.lower() for w in re.findall(r'\b\w{3,}\b', job_text) if w.lower() not in STOPWORDS])
        resume_words = set([w.lower() for w in re.findall(r'\b\w{3,}\b', resume_text) if w.lower() not in STOPWORDS])
                
        # Find matching words
        matching_nouns = job_words.intersection(resume_words)

        # Calculate match score
        match_score = (len(matching_nouns) / len(job_words)) * 100 if job_words else 0
        
        # Add matching words to skills_matched with their match percentages
        for noun in matching_nouns:
            match_percent = 100 / len(job_words) if job_words else 0
            skills_matched.append(f'{noun} ({match_percent:.1f}%)')
    
    # For recruiters: calculate match score and skills for each applicant
    applicant_match_info = {}
    if current_user.is_recruiter:
        for app in job.applications:
            user = app.user
            if user and user.skills:
                resume_text = (user.skills or '') + ' ' + (user.experience or '')
                job_text = (job.description or '') + ' ' + (job.requirements or '')
                job_words = set([w.lower() for w in re.findall(r'\b\w{3,}\b', job_text) if w.lower() not in STOPWORDS])
                resume_words = set([w.lower() for w in re.findall(r'\b\w{3,}\b', resume_text) if w.lower() not in STOPWORDS])
                matching_nouns = job_words.intersection(resume_words)
                score = (len(matching_nouns) / len(job_words)) * 100 if job_words else 0
                skills = [f'{noun} ({100/len(job_words):.1f}%)' for noun in matching_nouns] if job_words else []
                applicant_match_info[app.id] = {'score': score, 'skills': skills}
            else:
                applicant_match_info[app.id] = {'score': 0, 'skills': []}
    return render_template(
        'job_detail.html', 
        job=job,
        match_score=match_score,
        applied=applied,
        skills_matched=skills_matched,
        job_requirements=job.requirements,
        applicant_match_info=applicant_match_info
    )

@app.route('/apply_job/<int:job_id>')
@login_required
def apply_job(job_id):
    if not current_user.resume_path:
        flash('Please upload your resume first', 'error')
        return redirect(url_for('dashboard'))
    job = Job.query.get_or_404(job_id)
    # Prevent duplicate applications
    existing_application = JobApplication.query.filter_by(job_id=job_id, user_id=current_user.id).first()
    if existing_application:
        flash('You have already applied for this job!', 'info')
        return redirect(url_for('dashboard'))
    # Track performance metrics
    import time
    start_time = time.time()
    # Calculate match score based on skills
    user_skills = set(current_user.skills.lower().split(','))
    job_skills = set(job.skills.lower().split(','))
    match_score = len(user_skills.intersection(job_skills)) / len(job_skills) * 100 if job_skills else 0
    match_calc_time = time.time() - start_time
    application = JobApplication(
        job_id=job_id,
        user_id=current_user.id,
        match_score=match_score,
        match_calc_time=match_calc_time
    )
    db.session.add(application)
    db.session.commit()
    flash(f'Applied successfully! Match score: {match_score:.1f}%', 'success')
    return redirect(url_for('dashboard'))

@app.route('/dashboard', methods=['GET', 'POST'])
@login_required
def dashboard():
    if current_user.is_recruiter:
        jobs = Job.query.options(joinedload(Job.posted_by_user)).filter_by(posted_by=current_user.id).all()
        applications = JobApplication.query.join(Job).filter(Job.posted_by == current_user.id).all()
        return render_template('recruiter_dashboard.html', jobs=jobs, applications=applications)
    else:
        search_query = request.args.get('search', '').strip().lower()
        jobs = Job.query.options(joinedload(Job.posted_by_user)).filter_by(is_active=True).all()
        applications = JobApplication.query.filter_by(user_id=current_user.id).all()
        app_dict = {app.job_id: app for app in applications}
        job_match_scores = {}
        notifications = []
        if current_user.resume_path:
            resume_text = (current_user.skills or '') + ' ' + (current_user.experience or '')
            resume_words = set([w.lower() for w in re.findall(r'\b\w{3,}\b', resume_text) if w.lower() not in STOPWORDS])
            for job in jobs:
                job_text = (job.description or '') + ' ' + (job.requirements or '')
                job_words = set([w.lower() for w in re.findall(r'\b\w{3,}\b', job_text) if w.lower() not in STOPWORDS])
                matching_nouns = job_words.intersection(resume_words)
                match_score = (len(matching_nouns) / len(job_words)) * 100 if job_words else 0
                job_match_scores[job.id] = match_score
                if match_score > 30:
                    notifications.append({
                        'job_id': job.id,
                        'title': job.title,
                        'match_score': match_score
                    })
        else:
            for job in jobs:
                job_match_scores[job.id] = 0
        # Filter jobs by search query
        if search_query:
            jobs = [job for job in jobs if search_query in (job.title or '').lower() or search_query in (job.description or '').lower() or search_query in (job.requirements or '').lower()]
        # Sort jobs by match score descending
        jobs = sorted(jobs, key=lambda job: job_match_scores.get(job.id, 0), reverse=True)
        return render_template('job_seeker_dashboard.html', jobs=jobs, applications=applications, app_dict=app_dict, job_match_scores=job_match_scores, notifications=notifications, search_query=search_query)

@app.route('/delete_job/<int:job_id>', methods=['POST'])
@login_required
def delete_job(job_id):
    job = Job.query.get_or_404(job_id)
    if not current_user.is_recruiter or job.posted_by != current_user.id:
        flash('You are not authorized to delete this job.', 'danger')
        return redirect(url_for('job_detail', job_id=job_id))
    # Delete all applications for this job
    JobApplication.query.filter_by(job_id=job_id).delete()
    db.session.delete(job)
    db.session.commit()
    flash('Job deleted successfully.', 'success')
    return redirect(url_for('dashboard'))

@app.route('/admin_recruiter_dashboard')
@login_required
@admin_required
def admin_recruiter_dashboard():
    recruiters = User.query.filter_by(is_recruiter=True).all()
    return render_template('admin_recruiter_dashboard.html', recruiters=recruiters)

@app.route('/admin_jobseeker_dashboard')
@login_required
@admin_required
def admin_jobseeker_dashboard():
    jobseekers = User.query.filter_by(is_recruiter=False, is_admin=False).all()
    return render_template('admin_jobseeker_dashboard.html', jobseekers=jobseekers)

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)
