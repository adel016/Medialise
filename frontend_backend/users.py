from flask import Blueprint, render_template, redirect, url_for, request, flash, make_response, g, current_app, abort, jsonify
from functools import wraps
import models  # Changé de "from . import models" à "import models"
import json
import base64
from werkzeug.security import generate_password_hash, check_password_hash
import datetime
#from scripts.scraper import run_scraper
import os
import sys
import subprocess
import signal


# Création du Blueprint utilisateur
users_bp = Blueprint('users', __name__, template_folder='templates')

# Décorateur pour vérifier si l'utilisateur est connecté
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in request.cookies:
            flash("Vous devez être connecté pour accéder à cette page.", "warning")
            return redirect(url_for('users.login', next=request.url))
        return f(*args, **kwargs)
    return decorated_function

# Décorateur pour vérifier le rôle de l'utilisateur
def role_required(min_role):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            # pas connecté
            if 'role' not in request.cookies:
                return redirect(url_for('users.login'))

            role_cookie = request.cookies.get('role')
            try:
                role = int(role_cookie)
            except (TypeError, ValueError):
                # cookie corrompu ou ancien ("admin", "user", etc.) -> forcer reconnexion
                return redirect(url_for('users.login'))

            if role < min_role:
                abort(403)
            return f(*args, **kwargs)
        return decorated_function
    return decorator

# Configuration pour charger l'utilisateur avant chaque requête
@users_bp.before_app_request
def load_logged_in_user():
    """Charge l'utilisateur actuel dans g.user"""
    user_id = request.cookies.get('user_id')
    
    if user_id is None:
        g.user = None
    else:
        g.user = models.User.get_by_id(user_id)

# Routes utilisateur
@users_bp.route('/register', methods=['GET', 'POST'])
def register():
    """User registration page"""
    if request.cookies.get('user_id'):
        return redirect(url_for('index'))
        
    if request.method == 'POST':
        email = request.form.get('email')
        first_name = request.form.get('first_name', '')
        last_name = request.form.get('last_name', '')
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')
        role = int(request.form.get('role', 1))  # Default: Patient
        
        # Optional fields
        age = request.form.get('age')
        profession = request.form.get('profession')
        company = request.form.get('company')
        
        # Data validation
        if not email or not password or not confirm_password or not first_name or not last_name:
            flash("All fields marked with an asterisk are required.", "danger")
            return render_template('user/register.html')
            
        if password != confirm_password:
            flash("Passwords don't match.", "danger")
            return render_template('user/register.html')
        
        # Create user data dictionary
        user_data = {
            'email': email,
            'first_name': first_name,
            'last_name': last_name,
            'role': role
        }
        
        # Add optional fields
        if age:
            try:
                user_data['age'] = int(age)
            except ValueError:
                pass
        
        if profession:
            user_data['profession'] = profession
            
        if company and role == 2:  # Only for healthcare professionals
            user_data['company'] = company
        
        # Create the user
        user_id = models.User.create_with_data(email, password, user_data)
        
        if user_id:
            # Log the registration
            models.Log.create(user_id, models.Log.ACTION_REGISTER)
            
            flash("Your account has been created successfully. You can now log in.", "success")
            return redirect(url_for('users.login'))
        else:
            flash("This email address is already in use. Please choose another one.", "danger")
            
    return render_template('user/register.html')

@users_bp.route('/login', methods=['GET', 'POST'])
def login():
    """Page de connexion utilisateur"""
    if request.cookies.get('user_id'):
        return redirect(url_for('index'))
        
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        remember = request.form.get('remember') == 'on'
        
        # Vérification des identifiants
        user = models.User.check_password(email, password)
        if user:
            # Créer la réponse
            next_page = request.args.get('next')
            if next_page and next_page.startswith('/'):
                response = make_response(redirect(next_page))
            else:
                response = make_response(redirect(url_for('index')))
            
            # Définir les cookies
            cookie_options = {
                'httponly': True,
                'secure': request.is_secure,  # Utiliser HTTPS en production
                'samesite': 'Lax'
            }
            
            # Si "se souvenir de moi" est coché, définir max_age à 30 jours
            if remember:
                cookie_options['max_age'] = 30 * 24 * 60 * 60  # 30 jours en secondes
                
            response.set_cookie('user_id', str(user['_id']), **cookie_options)
            response.set_cookie('role', str(user['role']), **cookie_options)
            
            # Journaliser la connexion
            models.Log.create(str(user['_id']), models.Log.ACTION_LOGIN)
            
            flash("Connexion réussie!", "success")
            return response
        else:
            flash("Email ou mot de passe incorrect.", "danger")
            
    return render_template('user/login.html')

@users_bp.route('/logout')
def logout():
    """Déconnexion de l'utilisateur"""
    user_id = request.cookies.get('user_id')
    if user_id:
        # Journaliser la déconnexion
        models.Log.create(user_id, models.Log.ACTION_LOGOUT)
    
    # Créer la réponse et supprimer les cookies
    response = make_response(redirect(url_for('index')))
    response.delete_cookie('user_id')
    response.delete_cookie('role')
    
    flash("Vous avez été déconnecté avec succès.", "success")
    return response

@users_bp.route('/profile')
@login_required
def profile():
    """Profil de l'utilisateur connecté"""
    return render_template('user/profile.html', user=g.user)

@users_bp.route('/profile/edit', methods=['GET', 'POST'])
@login_required
def edit_profile():
    """Édition du profil utilisateur"""
    if request.method == 'POST':
        # Récupérer les données modifiées
        update_data = {
            'first_name': request.form.get('first_name'),
            'last_name': request.form.get('last_name')
        }
        
        # Ajouter les champs optionnels s'ils sont fournis
        optional_fields = ['age', 'profession', 'company']
        for field in optional_fields:
            if request.form.get(field):
                if field == 'age':
                    # Convertir en nombre
                    try:
                        update_data[field] = int(request.form.get(field))
                    except ValueError:
                        pass
                else:
                    update_data[field] = request.form.get(field)
        
        user_id = request.cookies.get('user_id')
        # Mettre à jour le profil
        if models.User.update(user_id, update_data):
            # Journaliser la mise à jour du profil
            models.Log.create(user_id, models.Log.ACTION_PROFILE_UPDATE)
            
            flash("Votre profil a été mis à jour avec succès.", "success")
        else:
            flash("Une erreur est survenue lors de la mise à jour de votre profil.", "danger")
            
        return redirect(url_for('users.profile'))
        
    return render_template('user/edit_profile.html', user=g.user)

@users_bp.route('/profile/password', methods=['GET', 'POST'])
@login_required
def change_password():
    """Modification du mot de passe"""
    if request.method == 'POST':
        current_password = request.form.get('current_password')
        new_password = request.form.get('new_password')
        confirm_password = request.form.get('confirm_password')
        
        # Vérifier que le mot de passe actuel est correct
        user = models.User.check_password(g.user['email'], current_password)
        if not user:
            flash("Mot de passe actuel incorrect.", "danger")
            return render_template('user/change_password.html')
            
        # Vérifier que les nouveaux mots de passe correspondent
        if new_password != confirm_password:
            flash("Les nouveaux mots de passe ne correspondent pas.", "danger")
            return render_template('user/change_password.html')
            
        user_id = request.cookies.get('user_id')
        # Mettre à jour le mot de passe
        if models.User.update_password(user_id, new_password):
            # Journaliser le changement de mot de passe
            models.Log.create(user_id, models.Log.ACTION_PASSWORD_CHANGE)
            
            flash("Votre mot de passe a été modifié avec succès.", "success")
            return redirect(url_for('users.profile'))
        else:
            flash("Une erreur est survenue lors de la modification de votre mot de passe.", "danger")
            
    return render_template('user/change_password.html')

# Routes pour les commentaires
@users_bp.route('/medicines/<medicine_id>/comments', methods=['POST'])
@login_required
def add_comment(medicine_id):
    """Ajouter un commentaire à un médicament"""
    content = request.form.get('content')
    rating = request.form.get('rating')
    
    if not content:
        flash("Le contenu du commentaire est obligatoire.", "danger")
        return redirect(url_for('medicine_details', id=medicine_id))  # Correction ici
        
    # Convertir rating en nombre si fourni
    rating_val = None
    if rating:
        try:
            rating_val = int(rating)
        except ValueError:
            pass
            
    # Déterminer la visibilité en fonction du rôle de l'utilisateur
    visibility = [1, 2, 3, 4]  # Par défaut, visible par tous les utilisateurs enregistrés
    
    user_id = request.cookies.get('user_id')
    # Créer le commentaire
    comment_id = models.Comment.create(
        user_id,
        medicine_id,
        content,
        visibility,
        rating_val
    )
    
    if comment_id:
        flash("Votre commentaire a été ajouté avec succès.", "success")
    else:
        flash("Une erreur est survenue lors de l'ajout de votre commentaire.", "danger")
        
    return redirect(url_for('medicine_details', id=medicine_id))  # Correction ici

@users_bp.route('/comments/<comment_id>/edit', methods=['POST'])
@login_required
def edit_comment(comment_id):
    """Modifier un commentaire"""
    content = request.form.get('content')
    rating = request.form.get('rating')
    medicine_id = request.form.get('medicine_id')
    
    if not content or not medicine_id:
        flash("Informations manquantes.", "danger")
        return redirect(url_for('medicine_details', id=medicine_id))  # Correction ici
        
    # Convertir rating en nombre si fourni
    update_data = {'content': content}
    if rating:
        try:
            update_data['rating'] = int(rating)
        except ValueError:
            pass
            
    user_id = request.cookies.get('user_id')
    # Mettre à jour le commentaire
    if models.Comment.update(comment_id, user_id, update_data):
        flash("Votre commentaire a été modifié avec succès.", "success")
    else:
        flash("Une erreur est survenue lors de la modification de votre commentaire.", "danger")
        
    return redirect(url_for('medicine_details', id=medicine_id))  # Correction ici

@users_bp.route('/comments/<comment_id>/delete', methods=['POST'])
@login_required
def delete_comment(comment_id):
    """Supprimer un commentaire"""
    medicine_id = request.form.get('medicine_id')
    
    if not medicine_id:
        abort(400)
        
    # Vérifier si l'utilisateur est admin
    is_admin = request.cookies.get('role') and int(request.cookies.get('role')) >= models.User.ROLE_ADMIN
    
    user_id = request.cookies.get('user_id')
    # Supprimer le commentaire
    if models.Comment.delete(comment_id, user_id, is_admin):
        flash("Le commentaire a été supprimé avec succès.", "success")
    else:
        flash("Une erreur est survenue lors de la suppression du commentaire.", "danger")
        
    return redirect(url_for('medicine_details', id=medicine_id))  # Correction ici

# Routes pour les favoris
@users_bp.route('/medicines/<medicine_id>/favorite', methods=['POST'])
@login_required
def toggle_favorite(medicine_id):
    """Ajouter/Retirer un médicament des favoris"""
    user_id = request.cookies.get('user_id')
    is_favorite = models.Interaction.create(
        user_id,
        medicine_id,
        models.Interaction.TYPE_FAVORITE
    )
    
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        # Réponse AJAX
        return {'status': 'success', 'is_favorite': is_favorite}
    
    # Redirection normale
    return redirect(url_for('main.medicine_details', id=medicine_id))

@users_bp.route('/favorites')
@login_required
def favorites():
    """Affiche les médicaments favoris de l'utilisateur"""
    user_id = g.user['_id']
    
    from models import Interaction
    favorites = Interaction.get_user_favorites(str(user_id))
    
    return render_template('user/favorites.html', favorites=favorites)

# Routes administratives
@users_bp.route('/admin/users')
@role_required(models.User.ROLE_ADMIN)
def admin_users():
    """Liste des utilisateurs pour l'administration"""
    page = request.args.get('page', 1, type=int)
    limit = 20
    skip = (page - 1) * limit
    
    filters = {}
    if request.args.get('role'):
        try:
            filters['role'] = int(request.args.get('role'))
        except ValueError:
            pass
            
    if request.args.get('status'):
        filters['status'] = request.args.get('status')
        
    users = models.User.list(filters, limit, skip)
    
    # Ajouter le nom du rôle à chaque utilisateur
    for user in users:
        user['role_name'] = models.User.get_role_name(user.get('role', 0))
    
    return render_template('admin/users.html', users=users, roles=models.User.ROLE_NAMES)

# Ajouter la route admin_roles qui était manquante
@users_bp.route('/admin/roles')
@role_required(models.User.ROLE_ADMIN)
def admin_roles():
    """Page d'administration des rôles"""
    # Récupérer tous les rôles
    roles = models.Role.get_all_roles()
    return render_template('admin/roles.html', roles=roles)

@users_bp.route('/admin/roles/<int:role_id>/permissions', methods=['POST'])
@role_required(models.User.ROLE_ADMIN)
def admin_update_role_permissions(role_id):
    """Mettre à jour les permissions d'un rôle"""
    if not request.is_json:
        return jsonify({"status": "error", "message": "Content-Type doit être application/json"}), 400
        
    data = request.get_json()
    permissions = data.get('permissions')
    
    if not permissions:
        return jsonify({"status": "error", "message": "Aucune permission fournie"}), 400
    
    if models.Role.update_permissions(role_id, permissions):
        return jsonify({"status": "success"})
    else:
        return jsonify({"status": "error", "message": "Mise à jour échouée"}), 500

@users_bp.route('/admin/users/<user_id>', methods=['GET', 'POST'])
@role_required(models.User.ROLE_ADMIN)
def admin_edit_user(user_id):
    """Édition d'un utilisateur par un administrateur"""
    user = models.User.get_by_id(user_id)
    if not user:
        abort(404)
        
    if request.method == 'POST':
        update_data = {}
        
        # Mettre à jour le rôle si fourni
        if request.form.get('role'):
            try:
                update_data['role'] = int(request.form.get('role'))
            except ValueError:
                flash("Rôle invalide.", "danger")
                return render_template('admin/edit_user.html', user=user, roles=models.User.ROLE_NAMES)
                
        # Mettre à jour le statut du compte si fourni
        if request.form.get('account_status'):
            update_data['account_status'] = request.form.get('account_status')
            
        # Appliquer les mises à jour
        if update_data and models.User.update(user_id, update_data):
            flash("L'utilisateur a été mis à jour avec succès.", "success")
        else:
            flash("Aucune modification n'a été appliquée.", "warning")
            
        return redirect(url_for('users.admin_users'))
        
    return render_template('admin/edit_user.html', user=user, roles=models.User.ROLE_NAMES)

@users_bp.route('/admin/database')
@role_required(models.User.ROLE_ADMIN)
def admin_database():
    """Page d'administration de la base de données"""
    # Utiliser la connexion MongoDB à travers mongo.db au lieu de current_app.db
    db = models.mongo.db
    
    # Récupérer les métadonnées de scraping
    metadata = db.metadata.find_one({"_id": "scraping_metadata"})
    
    # Obtenir des statistiques sur la base de données
    total_medicines = db.medicines.count_documents({})
    
    # Récupérer les médicaments les plus récemment scrapés
    latest_updates = list(db.medicines.find({}, {"title": 1, "update_date": 1, "last_scraped": 1})
                         .sort("last_scraped", -1).limit(5))
    
    # Récupérer des statistiques de base
    lab_count = len(db.medicines.distinct(
        "metadata.medicine_details.laboratoire",
        {"metadata.medicine_details.laboratoire": {"$nin": [None, ""]}}
    ))

    substance_count = len(db.medicines.distinct(
        "metadata.medicine_details.substances_actives",
        {"metadata.medicine_details.substances_actives": {"$exists": True, "$ne": []}}
    ))

    
    # Import datetime pour le contexte du template
    import datetime
    
    return render_template('user/admin_database.html', 
                          metadata=metadata,
                          total_medicines=total_medicines,
                          latest_updates=latest_updates,
                          lab_count=lab_count,
                          substance_count=substance_count,
                          now=datetime.datetime.now(),
                          datetime=datetime)  # Passer le module datetime au contexte

# ...existing code...

# filepath: c:\Users\adelf\Documents\BUT 3\Semestre 5\SAE\Medialise\frontend_backend\users.py
# ...existing code...
@users_bp.route('/admin/run_scraper', methods=['POST'])
@role_required(models.User.ROLE_ADMIN)
def admin_run_scraper():
    """
    Lance scrapers.run_agno en arrière-plan.
    - Empêche les doubles runs via un lock.
    - Écrit les logs dans scraping_current.log.
    - Stocke le PID pour pouvoir arrêter.
    """
    in_docker = os.path.exists("/app")

    if in_docker:
        project_root = "/app"   # /app = frontend_backend (monté par docker-compose)
        logs_dir = "/app/logs"
    else:
        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        logs_dir = os.path.join(os.path.dirname(__file__), "logs")

    os.makedirs(logs_dir, exist_ok=True)

    log_path = os.path.join(logs_dir, "scraping_current.log")
    lock_path = os.path.join(logs_dir, "scraping.lock")
    pid_path = os.path.join(logs_dir, "scraping.pid")

    # Si déjà en cours
    if os.path.exists(lock_path) and os.path.exists(pid_path):
        try:
            with open(pid_path, "r", encoding="utf-8") as f:
                pid = f.read().strip()
            return jsonify({"ok": True, "already_running": True, "pid": pid}), 200
        except Exception:
            return jsonify({"ok": True, "already_running": True}), 200

    # Reset log + lock
    with open(log_path, "w", encoding="utf-8") as f:
        f.write("Lancement du pipeline scrapers (run_agno)...\n")

    with open(lock_path, "w", encoding="utf-8") as f:
        f.write("locked\n")

    # Compat chemins scrapers : /app == frontend_backend dans docker
    # Les scrapers utilisent parfois "frontend_backend/..." => alias /app/frontend_backend -> /app
    if in_docker:
        fb_alias = os.path.join(project_root, "frontend_backend")
        try:
            if not os.path.exists(fb_alias):
                os.symlink(project_root, fb_alias)
        except Exception:
            # pas bloquant
            pass

    cmd = [sys.executable, "-m", "scrapers.run_agno"]

    # Démarrage en arrière-plan
    try:
        with open(log_path, "a", encoding="utf-8") as log_file:
            log_file.write(f"\n=== CMD: {' '.join(cmd)} ===\n")
            log_file.flush()

            proc = subprocess.Popen(
                cmd,
                cwd=project_root,
                stdout=log_file,
                stderr=log_file,
            )

        # Sauvegarde PID
        with open(pid_path, "w", encoding="utf-8") as f:
            f.write(str(proc.pid))

        return jsonify({"ok": True, "started": True, "pid": proc.pid}), 200

    except Exception as e:
        # Nettoyage lock si échec
        try:
            if os.path.exists(lock_path):
                os.remove(lock_path)
            if os.path.exists(pid_path):
                os.remove(pid_path)
        except Exception:
            pass

        with open(log_path, "a", encoding="utf-8") as log_file:
            log_file.write(f"\n=== ERREUR LANCEMENT ===\n{e}\n")
            log_file.flush()

        return jsonify({"ok": False, "error": str(e)}), 200

# ...existing code...
@users_bp.route('/admin/get_logs')
@role_required(models.User.ROLE_ADMIN)
def admin_get_logs():
    """
    Retourne la fin des logs de scraping pour l'interface admin.
    On lit UNIQUEMENT frontend_backend/logs/scraping.log en local,
    et /app/logs/scraping.log dans le conteneur.
    """
    tail = request.args.get('tail', default=200, type=int)

    if os.path.exists("/app"):
        logs_dir = "/app/logs"
    else:
        # dossier logs à côté de ce fichier
        logs_dir = os.path.join(os.path.dirname(__file__), "logs")

    log_path = os.path.join(logs_dir, "scraping_current.log")

    if not os.path.exists(log_path):
        return jsonify({
            "ok": False,
            "error": f"Aucun fichier de log scraping trouvé ({log_path})",
            "logs": []
        }), 200

    try:
        with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()

        if tail > 0 and len(lines) > tail:
            lines = lines[-tail:]

        lines = [line.rstrip("\n") for line in lines]

        return jsonify({"ok": True, "logs": lines})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e), "logs": []}), 200
# ...existing code...


@users_bp.route('/admin/stop_scraper', methods=['POST'])
@role_required(models.User.ROLE_ADMIN)
def admin_stop_scraper():
    in_docker = os.path.exists("/app")

    if in_docker:
        logs_dir = "/app/logs"
    else:
        logs_dir = os.path.join(os.path.dirname(__file__), "logs")

    pid_path = os.path.join(logs_dir, "scraping.pid")
    lock_path = os.path.join(logs_dir, "scraping.lock")
    log_path = os.path.join(logs_dir, "scraping_current.log")

    if not os.path.exists(pid_path):
        return jsonify({"ok": False, "error": "Aucun scraping en cours (pid absent)."}), 200

    try:
        with open(pid_path, "r", encoding="utf-8") as f:
            pid = int(f.read().strip())

        # tente SIGTERM
        os.kill(pid, signal.SIGTERM)

        # nettoyage
        if os.path.exists(pid_path):
            os.remove(pid_path)
        if os.path.exists(lock_path):
            os.remove(lock_path)

        with open(log_path, "a", encoding="utf-8") as log_file:
            log_file.write("\n=== STOP demandé (SIGTERM) ===\n")
            log_file.flush()

        return jsonify({"ok": True, "stopped": True, "pid": pid}), 200

    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 200


# @users_bp.route('/admin/scraper/status', methods=['GET'])
# @role_required(models.User.ROLE_ADMIN)
# def admin_scraper_status():
#     """Retourne l'état actuel du processus de scraping"""
#     # Vérifier si un processus de scraping est en cours
#     if hasattr(run_scraper, 'is_running') and run_scraper.is_running:
#         return jsonify({
#             "status": "running",
#             "progress": run_scraper.progress
#         })
#     else:
#         return jsonify({
#             "status": "idle"
#         })

# @users_bp.route('/admin/scraper/logs', methods=['GET'])
# @role_required(models.User.ROLE_ADMIN)
# def admin_scraper_logs():
#     """Renvoie les logs du scraping depuis un ID donné"""
#     since_id = int(request.args.get('since', 0))
    
#     # Récupérer les logs avec un ID supérieur à since_id
#     filtered_logs = [log for log in getattr(run_scraper, 'logs', []) if log['id'] > since_id]
    
#     # Limiter à 100 logs maximum pour éviter de surcharger la réponse
#     filtered_logs = filtered_logs[-100:] if len(filtered_logs) > 100 else filtered_logs
    
#     return jsonify({
#         "logs": filtered_logs
#     })

# @users_bp.route('/admin/scraper/stop', methods=['POST'])
# @role_required(models.User.ROLE_ADMIN)


# Fonction pour initialiser le blueprint avec l'application Flask
def init_users(app):
    """Enregistre le blueprint utilisateurs dans l'application Flask"""
    app.register_blueprint(users_bp)
