from flask_pymongo import PyMongo
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
from bson.objectid import ObjectId
from flask import current_app

# Initialize PyMongo with None - will be configured in the application
mongo = PyMongo()

class Role:
    """Model for the roles collection in MongoDB"""
    
    # Default role IDs (keeping the same IDs for compatibility)
    VISITOR = 0
    PATIENT = 1
    PROFESSIONAL = 2
    RESEARCHER = 3
    ADMIN = 4
    INDIVIDUAL = 5
    STUDENT = 6
    
    @staticmethod
    def ensure_default_roles():
        """Ensure all default roles exist in the database"""
        default_roles = [
            {
                "_id": Role.VISITOR,
                "name": "Visitor",
                "display_name": "Visiteur",
                "description": "Basic access with limited permissions",
                "permissions": {
                    "read_public_content": True,
                    "search_medicines": True,
                    "add_comments": False,
                    "add_favorites": False,
                    "view_profile": False,
                    "edit_profile": False
                }
            },
            {
                "_id": Role.PATIENT,
                "name": "Patient",
                "display_name": "Patient",
                "description": "Regular user account for patients",
                "permissions": {
                    "read_public_content": True,
                    "search_medicines": True,
                    "add_comments": True,
                    "add_favorites": True,
                    "view_profile": True,
                    "edit_profile": True
                }
            },
            {
                "_id": Role.PROFESSIONAL,
                "name": "Healthcare Professional",
                "display_name": "Professionnel de santé",
                "description": "Account for healthcare workers with additional privileges",
                "permissions": {
                    "read_public_content": True,
                    "search_medicines": True,
                    "add_comments": True,
                    "add_favorites": True,
                    "view_profile": True,
                    "edit_profile": True,
                    "professional_content": True,
                    "suggest_updates": True
                }
            },
            {
                "_id": Role.RESEARCHER,
                "name": "Researcher",
                "display_name": "Chercheur",
                "description": "Account for medical researchers",
                "permissions": {
                    "read_public_content": True,
                    "search_medicines": True,
                    "add_comments": True,
                    "add_favorites": True,
                    "view_profile": True,
                    "edit_profile": True,
                    "research_data_access": True
                }
            },
            {
                "_id": Role.ADMIN,
                "name": "Administrator",
                "display_name": "Administrateur",
                "description": "Full access to all system functions",
                "permissions": {
                    "read_public_content": True,
                    "search_medicines": True,
                    "add_comments": True,
                    "add_favorites": True,
                    "view_profile": True,
                    "edit_profile": True,
                    "admin_panel": True,
                    "manage_users": True,
                    "manage_content": True,
                    "run_scrapers": True,
                    "system_settings": True
                }
            },
            {
                "_id": Role.INDIVIDUAL,
                "name": "Individual",
                "display_name": "Particulier",
                "description": "Regular individual user account",
                "permissions": {
                    "read_public_content": True,
                    "search_medicines": True,
                    "add_comments": True,
                    "add_favorites": True,
                    "view_profile": True,
                    "edit_profile": True
                }
            },
            {
                "_id": Role.STUDENT,
                "name": "Student",
                "display_name": "Étudiant",
                "description": "Account for medical or pharmacy students",
                "permissions": {
                    "read_public_content": True,
                    "search_medicines": True,
                    "add_comments": True,
                    "add_favorites": True,
                    "view_profile": True,
                    "edit_profile": True,
                    "educational_content": True
                }
            }
        ]
        
        for role in default_roles:
            # Use upsert to insert if not exists or update if exists
            mongo.db.roles.update_one(
                {"_id": role["_id"]}, 
                {"$set": role}, 
                upsert=True
            )
    
    @staticmethod
    def get_by_id(role_id):
        """Get a role by its ID"""
        return mongo.db.roles.find_one({"_id": int(role_id)})
    
    @staticmethod
    def get_all_roles():
        """Get all roles"""
        return list(mongo.db.roles.find().sort("_id", 1))
    
    @staticmethod
    def check_permission(role_id, permission_name):
        """Check if a role has a specific permission"""
        role = Role.get_by_id(role_id)
        if not role or "permissions" not in role:
            return False
        return role["permissions"].get(permission_name, False)
    
    @staticmethod
    def update_permissions(role_id, permissions):
        """Update permissions for a role"""
        return mongo.db.roles.update_one(
            {"_id": int(role_id)},
            {"$set": {"permissions": permissions}}
        ).modified_count > 0

# Update User class to use Role model
class User:
    """Model for the users collection in MongoDB"""
    
    # Keep role constants for backward compatibility and easy reference
    ROLE_VISITOR = Role.VISITOR
    ROLE_PATIENT = Role.PATIENT
    ROLE_PROFESSIONAL = Role.PROFESSIONAL
    ROLE_RESEARCHER = Role.RESEARCHER
    ROLE_ADMIN = Role.ADMIN
    ROLE_INDIVIDUAL = Role.INDIVIDUAL
    ROLE_STUDENT = Role.STUDENT
    
    # Role names dict is kept for backward compatibility
    ROLE_NAMES = {
        ROLE_VISITOR: "Visitor",
        ROLE_PATIENT: "Patient",
        ROLE_PROFESSIONAL: "Healthcare Professional",
        ROLE_RESEARCHER: "Researcher",
        ROLE_ADMIN: "Administrator", 
        ROLE_INDIVIDUAL: "Individual",
        ROLE_STUDENT: "Student"
    }
    
    # Display names in French for UI
    ROLE_DISPLAY_NAMES = {
        ROLE_VISITOR: "Visiteur",
        ROLE_PATIENT: "Patient",
        ROLE_PROFESSIONAL: "Professionnel de santé",
        ROLE_RESEARCHER: "Chercheur",
        ROLE_ADMIN: "Administrateur",
        ROLE_INDIVIDUAL: "Particulier",
        ROLE_STUDENT: "Étudiant"
    }
    
    STATUS_ACTIVE = 'active'
    STATUS_INACTIVE = 'inactive'
    STATUS_VERIFIED = 'verified'
    
    @staticmethod
    def get_role_name(role_id):
        """Get the name of a role by its ID"""
        role = Role.get_by_id(role_id)
        if role and "name" in role:
            return role["name"]
        return User.ROLE_NAMES.get(int(role_id), "Unknown Role")
    
    @staticmethod
    def get_role_display_name(role_id):
        """Get the display name of a role by its ID"""
        role = Role.get_by_id(role_id)
        if role and "display_name" in role:
            return role["display_name"]
        return User.ROLE_DISPLAY_NAMES.get(int(role_id), "Rôle inconnu")
    
    @staticmethod
    def has_permission(user_id, permission_name):
        """Check if a user has a specific permission"""
        user = User.get_by_id(user_id)
        if not user or "role" not in user:
            return False
        return Role.check_permission(user["role"], permission_name)

    @staticmethod
    def create_with_data(email, password, user_data):
        """Create a new user with provided data"""
        # Check if email is already in use
        if mongo.db.users.find_one({"email": email}):
            return None
            
        # Prepare basic data
        full_user_data = {
            "email": email,
            "password_hash": generate_password_hash(password, method='pbkdf2:sha256', salt_length=10),
            "created_at": datetime.utcnow(),
            "status": User.STATUS_ACTIVE
        }
        
        # Add fields from user_data
        full_user_data.update(user_data)
        
        # Insert the user
        result = mongo.db.users.insert_one(full_user_data)
        return str(result.inserted_id)
    
    @staticmethod
    def create(email, password, first_name, last_name, role=1):
        """Create a new user with basic fields"""
        user_data = {
            "first_name": first_name,
            "last_name": last_name,
            "role": role
        }
        return User.create_with_data(email, password, user_data)
    
    @staticmethod
    def get_by_id(user_id):
        """Retrieve a user by their ID"""
        try:
            user = mongo.db.users.find_one({"_id": ObjectId(user_id)})
            return user
        except:
            return None
    
    @staticmethod
    def get_by_email(email):
        """Retrieve a user by their email"""
        return mongo.db.users.find_one({"email": email})
    
    @staticmethod
    def check_password(email, password):
        """Check the password for a given email"""
        user = User.get_by_email(email)
        if not user:
            return None
            
        if check_password_hash(user["password_hash"], password):
            # Update the last login date
            mongo.db.users.update_one(
                {"_id": user["_id"]}, 
                {"$set": {"last_login": datetime.utcnow()}}
            )
            return user
        
        return None
    
    @staticmethod
    def update(user_id, update_data):
        """Update a user's data"""
        # Do not allow updating certain sensitive fields
        if "password_hash" in update_data or "email" in update_data:
            return False
            
        result = mongo.db.users.update_one(
            {"_id": ObjectId(user_id)},
            {"$set": update_data}
        )
        return result.modified_count > 0
    
    @staticmethod
    def update_password(user_id, new_password):
        """Update a user's password"""
        result = mongo.db.users.update_one(
            {"_id": ObjectId(user_id)},
            {"$set": {"password_hash": generate_password_hash(new_password, method='pbkdf2:sha256', salt_length=10)}}
        )
        return result.modified_count > 0
        
    @staticmethod
    def list(filters=None, limit=20, skip=0):
        """List users with optional filters"""
        query = {}
        if filters:
            if "role" in filters:
                query["role"] = filters["role"]
            if "status" in filters:
                query["status"] = filters["status"]
                
        return list(mongo.db.users.find(query).limit(limit).skip(skip))


class Comment:
    """Model for the comments collection in MongoDB"""
    
    STATUS_PUBLISHED = 'published'
    STATUS_MODERATED = 'moderated'
    STATUS_DELETED = 'deleted'
    
    @staticmethod
    def create(user_id, medicine_id, content, visibility=None, rating=None):
        """Create a new comment"""
        # By default, visible to all registered users
        if visibility is None:
            visibility = [1, 2, 3, 4]  # All roles except visitor
            
        comment_data = {
            "user_id": ObjectId(user_id),
            "medicine_id": medicine_id,  # medicine_id is already a string
            "content": content,
            "visibility": visibility,
            "timestamp": datetime.utcnow(),
            "status": Comment.STATUS_PUBLISHED
        }
        
        if rating is not None:
            comment_data["rating"] = max(1, min(5, rating))  # Limit between 1 and 5
            
        result = mongo.db.comments.insert_one(comment_data)
        return str(result.inserted_id)
    
    @staticmethod
    def get_by_id(comment_id):
        """Retrieve a comment by its ID"""
        try:
            comment = mongo.db.comments.find_one({"_id": ObjectId(comment_id)})
            return comment
        except:
            return None
    
    @staticmethod
    def get_for_medicine(medicine_id, user_role=None):
        """Retrieve comments for a medicine with filtering by role"""
        query = {
            "medicine_id": medicine_id,
            "status": Comment.STATUS_PUBLISHED
        }
        
        # Filter comments by visibility according to the user's role
        if user_role is not None:
            query["visibility"] = user_role
            
        return list(mongo.db.comments.find(query).sort("timestamp", -1))
    
    @staticmethod
    def update(comment_id, user_id, update_data):
        """Update a comment (only by the author)"""
        # Check that the user is the author of the comment
        comment = Comment.get_by_id(comment_id)
        if not comment or str(comment["user_id"]) != str(user_id):
            return False
            
        # Allow only updating content and rating
        safe_update = {}
        if "content" in update_data:
            safe_update["content"] = update_data["content"]
        if "rating" in update_data:
            safe_update["rating"] = max(1, min(5, update_data["rating"]))
            
        if safe_update:
            safe_update["last_edited"] = datetime.utcnow()
            result = mongo.db.comments.update_one(
                {"_id": ObjectId(comment_id)},
                {"$set": safe_update}
            )
            return result.modified_count > 0
            
        return False
    
    @staticmethod
    def delete(comment_id, user_id=None, admin=False):
        """Delete a comment (soft delete) by the author or an admin"""
        if admin:
            # If it's an admin, no need to check the author
            query = {"_id": ObjectId(comment_id)}
        else:
            # Otherwise, check that the user is the author
            query = {
                "_id": ObjectId(comment_id),
                "user_id": ObjectId(user_id)
            }
            
        result = mongo.db.comments.update_one(
            query,
            {"$set": {"status": Comment.STATUS_DELETED}}
        )
        return result.modified_count > 0


class Interaction:
    """Model for the interactions collection in MongoDB"""
    
    TYPE_FAVORITE = 'favorite'
    TYPE_VIEW = 'view'
    TYPE_SEARCH = 'search'
    
    @staticmethod
    def create(user_id, medicine_id, interaction_type):
        """Create or update a user-medicine interaction"""
        # For favorites, check if it already exists and toggle
        if interaction_type == Interaction.TYPE_FAVORITE:
            existing = mongo.db.interactions.find_one({
                "user_id": ObjectId(user_id),
                "medicine_id": medicine_id,
                "type": Interaction.TYPE_FAVORITE
            })
            
            if existing:
                # If it already exists, delete (toggle)
                mongo.db.interactions.delete_one({"_id": existing["_id"]})
                return False
                
        # Create the new interaction
        interaction_data = {
            "user_id": ObjectId(user_id),
            "medicine_id": medicine_id,
            "type": interaction_type,
            "timestamp": datetime.utcnow()
        }
        
        mongo.db.interactions.insert_one(interaction_data)
        return True
    
    @staticmethod
    def get_favorites(user_id):
        """Retrieve the user's favorite medicines"""
        interactions = mongo.db.interactions.find({
            "user_id": ObjectId(user_id),
            "type": Interaction.TYPE_FAVORITE
        })
        
        return [i["medicine_id"] for i in interactions]
    
    @staticmethod
    def is_favorite(user_id, medicine_id):
        """Check if a medicine is in the favorites"""
        return mongo.db.interactions.find_one({
            "user_id": ObjectId(user_id),
            "medicine_id": medicine_id,
            "type": Interaction.TYPE_FAVORITE
        }) is not None

    @staticmethod
    def add_favorite(user_id, medicine_id):
        """Ajoute un médicament aux favoris d'un utilisateur"""
        result = mongo.db.interactions.update_one(
            {"user_id": user_id, "medicine_id": medicine_id},
            {"$set": {"type": "favorite", "created_at": datetime.now()}},
            upsert=True
        )
        return result.modified_count > 0 or result.upserted_id is not None
    
    @staticmethod
    def remove_favorite(user_id, medicine_id):
        """Supprime un médicament des favoris d'un utilisateur"""
        result = mongo.db.interactions.delete_one(
            {"user_id": user_id, "medicine_id": medicine_id, "type": "favorite"}
        )
        return result.deleted_count > 0
    
    @staticmethod
    def is_favorite(user_id, medicine_id):
        """Vérifie si un médicament est dans les favoris d'un utilisateur"""
        interaction = mongo.db.interactions.find_one(
            {"user_id": user_id, "medicine_id": medicine_id, "type": "favorite"}
        )
        return interaction is not None
    
    @staticmethod
    def get_user_favorites(user_id):
        """Récupère tous les médicaments favoris d'un utilisateur"""
        favorites = list(mongo.db.interactions.find(
            {"user_id": user_id, "type": "favorite"}
        ).sort("created_at", -1))
        
        # Récupérer les détails des médicaments pour chaque favori
        medicine_ids = [ObjectId(fav["medicine_id"]) for fav in favorites]
        medicines = list(mongo.db.medicines.find({"_id": {"$in": medicine_ids}}))
        
        # Organiser les médicaments sous forme de dictionnaire pour un accès facile
        medicines_dict = {str(med["_id"]): med for med in medicines}
        
        # Ajouter les détails des médicaments aux favoris
        for favorite in favorites:
            med_id = favorite["medicine_id"]
            if med_id in medicines_dict:
                favorite["medicine"] = medicines_dict[med_id]
        
        return favorites


class Log:
    """Model for the logs collection in MongoDB"""
    
    ACTION_LOGIN = 'login'
    ACTION_LOGOUT = 'logout'
    ACTION_REGISTER = 'register'
    ACTION_PASSWORD_CHANGE = 'password_change'
    ACTION_PROFILE_UPDATE = 'profile_update'
    
    @staticmethod
    def create(user_id, action, details=None):
        """Create a log entry"""
        log_data = {
            "user_id": ObjectId(user_id),
            "action": action,
            "timestamp": datetime.utcnow()
        }
        
        if details:
            log_data["details"] = details
            
        mongo.db.logs.insert_one(log_data)

# Initialization function to configure models with the Flask app
def init_db(app):
    """Initialize the database connection"""
    mongo.init_app(app)
    
    # S'assurer que l'application a accès à la base de données MongoDB
    if not hasattr(app, 'db'):
        app.db = mongo.db
    
    # Create indexes if needed
    with app.app_context():
        # Ensure all default roles exist
        Role.ensure_default_roles()
        
        # Index on user emails (unique)
        mongo.db.users.create_index("email", unique=True)
        
        # Index on comments for efficient search
        mongo.db.comments.create_index([
            ("medicine_id", 1),
            ("status", 1),
            ("visibility", 1)
        ])
        
        # Index on interactions
        mongo.db.interactions.create_index([
            ("user_id", 1),
            ("medicine_id", 1),
            ("type", 1)
        ], unique=True)
