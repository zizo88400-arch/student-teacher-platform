import os, re
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from flask import Flask, render_template, redirect, url_for, flash, request, abort, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from flask_wtf import FlaskForm, CSRFProtect
from wtforms import StringField, PasswordField, SelectField, TextAreaField, FileField, SubmitField
from wtforms.validators import DataRequired, Email, Length, EqualTo, Optional, URL

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)
ALLOWED_EXTENSIONS = {"pdf", "doc", "docx", "ppt", "pptx", "png", "jpg", "jpeg"}
GRADES = [
    "الأول الإعدادي", "الثاني الإعدادي", "الثالث الإعدادي",
    "الأول الثانوي", "الثاني الثانوي", "الثالث الثانوي"
]

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "change-this-secret-before-deployment")
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("DATABASE_URL", f"sqlite:///{BASE_DIR / 'platform.db'}")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["UPLOAD_FOLDER"] = str(UPLOAD_DIR)
app.config["MAX_CONTENT_LENGTH"] = 20 * 1024 * 1024

db = SQLAlchemy(app)
csrf = CSRFProtect(app)
login_manager = LoginManager(app)
login_manager.login_view = "login"
login_manager.login_message = "سجّل دخولك الأول."
login_manager.login_message_category = "warning"


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(150), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False)  # student / teacher / admin
    grade = db.Column(db.String(50))                  # للطالب
    subject = db.Column(db.String(100))               # للمعلم
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Resource(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(180), nullable=False)
    description = db.Column(db.Text)
    resource_type = db.Column(db.String(20), nullable=False)  # youtube / file / link
    grade = db.Column(db.String(50), nullable=False)
    subject = db.Column(db.String(100), default="عام")
    url = db.Column(db.String(500))
    filename = db.Column(db.String(255))
    teacher_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class News(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(180), nullable=False)
    body = db.Column(db.Text, nullable=False)
    source_url = db.Column(db.String(500))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class UsefulLink(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(150), nullable=False)
    url = db.Column(db.String(500), nullable=False)
    audience = db.Column(db.String(20), default="all")  # all / student / teacher
    description = db.Column(db.String(300))


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


class RegisterForm(FlaskForm):
    name = StringField("الاسم", validators=[DataRequired(), Length(min=2, max=100)])
    email = StringField("البريد الإلكتروني", validators=[DataRequired(), Email(), Length(max=150)])
    password = PasswordField("كلمة المرور", validators=[DataRequired(), Length(min=8)])
    confirm = PasswordField("تأكيد كلمة المرور", validators=[DataRequired(), EqualTo("password")])
    role = SelectField("نوع الحساب", choices=[("student", "طالب"), ("teacher", "معلم")])
    grade = SelectField("الصف الدراسي", choices=[("", "اختر الصف")] + [(g, g) for g in GRADES])
    subject = StringField("المادة (للمعلم)", validators=[Optional(), Length(max=100)])
    submit = SubmitField("إنشاء الحساب")


class LoginForm(FlaskForm):
    email = StringField("البريد الإلكتروني", validators=[DataRequired(), Email()])
    password = PasswordField("كلمة المرور", validators=[DataRequired()])
    submit = SubmitField("دخول")


class ResourceForm(FlaskForm):
    title = StringField("عنوان المحتوى", validators=[DataRequired(), Length(max=180)])
    description = TextAreaField("وصف مختصر", validators=[Optional()])
    grade = SelectField("الصف الدراسي", choices=[(g, g) for g in GRADES], validators=[DataRequired()])
    subject = StringField("المادة", validators=[DataRequired(), Length(max=100)])
    resource_type = SelectField("نوع المحتوى", choices=[
        ("youtube", "فيديو يوتيوب"), ("link", "رابط خارجي"), ("file", "ملف مرفوع")
    ])
    url = StringField("رابط يوتيوب أو الرابط الخارجي", validators=[Optional(), Length(max=500)])
    file = FileField("الملف (PDF أو Office أو صورة)")
    submit = SubmitField("نشر المحتوى")


class NewsForm(FlaskForm):
    title = StringField("عنوان الخبر", validators=[DataRequired(), Length(max=180)])
    body = TextAreaField("تفاصيل الخبر", validators=[DataRequired()])
    source_url = StringField("رابط المصدر (اختياري)", validators=[Optional(), Length(max=500)])
    submit = SubmitField("نشر الخبر")


class LinkForm(FlaskForm):
    title = StringField("اسم الموقع أو المنصة", validators=[DataRequired(), Length(max=150)])
    url = StringField("الرابط", validators=[DataRequired(), URL(), Length(max=500)])
    audience = SelectField("موجّه إلى", choices=[("all", "الكل"), ("student", "الطلاب"), ("teacher", "المعلمين")])
    description = StringField("وصف مختصر", validators=[Optional(), Length(max=300)])
    submit = SubmitField("إضافة الرابط")


def is_allowed(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def youtube_embed(url):
    try:
        parsed = urlparse(url)
        if parsed.netloc.endswith("youtu.be"):
            video_id = parsed.path.strip("/")
        elif "youtube.com" in parsed.netloc:
            video_id = parse_qs(parsed.query).get("v", [""])[0]
            if not video_id and parsed.path.startswith("/embed/"):
                video_id = parsed.path.split("/embed/")[1].split("/")[0]
        else:
            return None
        if re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id or ""):
            return f"https://www.youtube-nocookie.com/embed/{video_id}"
    except Exception:
        pass
    return None


@app.context_processor
def inject_globals():
    return {"grades": GRADES}


@app.route("/")
def index():
    latest_news = News.query.order_by(News.created_at.desc()).limit(5).all()
    links = UsefulLink.query.filter_by(audience="all").limit(6).all()
    return render_template("index.html", news=latest_news, links=links)


@app.route("/register", methods=["GET", "POST"])
def register():
    form = RegisterForm()
    if form.validate_on_submit():
        email = form.email.data.strip().lower()
        if User.query.filter_by(email=email).first():
            flash("البريد الإلكتروني مسجل بالفعل.", "danger")
        elif form.role.data == "student" and not form.grade.data:
            flash("اختار الصف الدراسي.", "warning")
        else:
            user = User(
                name=form.name.data.strip(), email=email, role=form.role.data,
                grade=form.grade.data if form.role.data == "student" else None,
                subject=form.subject.data.strip() if form.role.data == "teacher" else None
            )
            user.set_password(form.password.data)
            db.session.add(user)
            db.session.commit()
            login_user(user)
            flash("تم إنشاء الحساب بنجاح.", "success")
            return redirect(url_for("dashboard"))
    return render_template("register.html", form=form)


@app.route("/login", methods=["GET", "POST"])
def login():
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data.strip().lower()).first()
        if user and user.check_password(form.password.data):
            login_user(user)
            return redirect(url_for("dashboard"))
        flash("البريد الإلكتروني أو كلمة المرور غير صحيحة.", "danger")
    return render_template("login.html", form=form)


@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("تم تسجيل الخروج.", "info")
    return redirect(url_for("index"))


@app.route("/dashboard")
@login_required
def dashboard():
    news = News.query.order_by(News.created_at.desc()).limit(6).all()
    if current_user.role == "student":
        resources = Resource.query.filter_by(grade=current_user.grade).order_by(Resource.created_at.desc()).all()
        links = UsefulLink.query.filter(UsefulLink.audience.in_(["all", "student"])).all()
        return render_template("student.html", resources=resources, news=news, links=links)
    if current_user.role == "teacher":
        resources = Resource.query.filter_by(teacher_id=current_user.id).order_by(Resource.created_at.desc()).all()
        links = UsefulLink.query.filter(UsefulLink.audience.in_(["all", "teacher"])).all()
        return render_template("teacher.html", resources=resources, news=news, links=links)
    return redirect(url_for("admin_dashboard"))


@app.route("/resource/new", methods=["GET", "POST"])
@login_required
def new_resource():
    if current_user.role not in ("teacher", "admin"):
        abort(403)
    form = ResourceForm()
    if form.validate_on_submit():
        kind = form.resource_type.data
        saved_name = None
        url = (form.url.data or "").strip() or None
        if kind in ("youtube", "link"):
            if not url or not urlparse(url).scheme in ("http", "https") or not urlparse(url).netloc:
                flash("أدخل رابطًا صحيحًا يبدأ بـ https:// أو http://", "danger")
                return render_template("resource_form.html", form=form)
            if kind == "youtube" and not youtube_embed(url):
                flash("رابط يوتيوب غير واضح. استخدم رابط الفيديو العادي.", "danger")
                return render_template("resource_form.html", form=form)
        else:
            uploaded = form.file.data
            if not uploaded or not uploaded.filename or not is_allowed(uploaded.filename):
                flash("ارفع ملفًا من الأنواع المسموح بها: PDF أو Word أو PowerPoint أو صورة.", "danger")
                return render_template("resource_form.html", form=form)
            safe_name = secure_filename(uploaded.filename)
            saved_name = f"{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')}_{safe_name}"
            uploaded.save(UPLOAD_DIR / saved_name)
            url = None
        resource = Resource(
            title=form.title.data.strip(), description=form.description.data,
            resource_type=kind, grade=form.grade.data, subject=form.subject.data.strip(),
            url=url, filename=saved_name, teacher_id=current_user.id
        )
        db.session.add(resource)
        db.session.commit()
        flash("تم نشر المحتوى.", "success")
        return redirect(url_for("dashboard"))
    return render_template("resource_form.html", form=form)


@app.route("/uploads/<path:filename>")
@login_required
def uploaded_file(filename):
    resource = Resource.query.filter_by(filename=filename).first_or_404()
    if current_user.role == "student" and resource.grade != current_user.grade:
        abort(403)
    if current_user.role == "teacher" and resource.teacher_id != current_user.id:
        abort(403)
    return send_from_directory(app.config["UPLOAD_FOLDER"], filename, as_attachment=True)


@app.route("/news/new", methods=["GET", "POST"])
@login_required
def new_news():
    if current_user.role != "admin":
        abort(403)
    form = NewsForm()
    if form.validate_on_submit():
        db.session.add(News(title=form.title.data, body=form.body.data, source_url=form.source_url.data or None))
        db.session.commit()
        flash("تم نشر الخبر.", "success")
        return redirect(url_for("admin_dashboard"))
    return render_template("news_form.html", form=form)


@app.route("/links/new", methods=["GET", "POST"])
@login_required
def new_link():
    if current_user.role != "admin":
        abort(403)
    form = LinkForm()
    if form.validate_on_submit():
        db.session.add(UsefulLink(title=form.title.data, url=form.url.data, audience=form.audience.data,
                                  description=form.description.data))
        db.session.commit()
        flash("تمت إضافة الرابط.", "success")
        return redirect(url_for("admin_dashboard"))
    return render_template("link_form.html", form=form)


@app.route("/admin")
@login_required
def admin_dashboard():
    if current_user.role != "admin":
        abort(403)
    users = User.query.order_by(User.created_at.desc()).all()
    resources = Resource.query.order_by(Resource.created_at.desc()).limit(20).all()
    news = News.query.order_by(News.created_at.desc()).all()
    links = UsefulLink.query.order_by(UsefulLink.id.desc()).all()
    return render_template("admin.html", users=users, resources=resources, news=news, links=links)


@app.errorhandler(403)
def forbidden(_):
    return render_template("message.html", title="غير مسموح", message="ليس لديك صلاحية لفتح الصفحة دي."), 403


@app.errorhandler(404)
def not_found(_):
    return render_template("message.html", title="الصفحة غير موجودة", message="الرابط المطلوب غير موجود."), 404


with app.app_context():
    db.create_all()
    # أنشئ حساب المدير الأول من متغيرات البيئة فقط، ولا تضع كلمة مروره داخل الكود.
    admin_email = os.environ.get("ADMIN_EMAIL")
    admin_password = os.environ.get("ADMIN_PASSWORD")
    if admin_email and admin_password and not User.query.filter_by(email=admin_email.lower()).first():
        admin = User(name="مدير المنصة", email=admin_email.lower(), role="admin")
        admin.set_password(admin_password)
        db.session.add(admin)
        db.session.commit()


if __name__ == "__main__":
    app.run(debug=os.environ.get("FLASK_DEBUG") == "1")
