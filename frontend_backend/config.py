import os

class Config:
    """Configuration de base pour l'application MedicSearch"""
    
    # Configuration MongoDB
    MONGO_URI = 'mongodb://mongo:27017/medicsearch'
    
    # Configuration de sécurité
    # SECRET_KEY reste nécessaire pour les flash messages et la protection CSRF
    SECRET_KEY = os.environ.get('SECRET_KEY', 'e8b7c9d2f5a3b1e4c6d8f0a9b2e7d5c1')
    
    # Configuration du cache
    CACHE_TYPE = os.environ.get('CACHE_TYPE', 'simple')
    CACHE_DEFAULT_TIMEOUT = 300
    
    # Configuration des logs
    LOG_LEVEL = os.environ.get('LOG_LEVEL', 'INFO')
    
    # Options de pagination par défaut
    DEFAULT_PAGE_SIZE = 10
    MAX_PAGE_SIZE = 100
    
    # Configuration des cookies
    SESSION_COOKIE_SECURE = os.environ.get('SESSION_COOKIE_SECURE', 'False').lower() == 'true'
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    
    # Configuration de l'IA
    AI_API_KEY = os.environ.get('AI_API_KEY')

class DevelopmentConfig(Config):
    """Configuration pour l'environnement de développement"""
    DEBUG = True

class ProductionConfig(Config):
    """Configuration pour l'environnement de production"""
    DEBUG = False
    
    # En production, assurez-vous de définir SECRET_KEY via une variable d'environnement
    # et n'utilisez pas la valeur par défaut!
    
    # Options de cache plus performantes pour la production
    CACHE_TYPE = 'redis'
    CACHE_REDIS_URL = os.environ.get('REDIS_URL', 'redis://localhost:6379/0')

class TestingConfig(Config):
    """Configuration pour les tests"""
    TESTING = True
    MONGO_URI = 'mongodb://mongo:27017/medicsearch_test'

# Dictionnaire pour sélectionner la configuration selon l'environnement
config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'testing': TestingConfig,
    'default': DevelopmentConfig
}

# Fonction pour obtenir la configuration actuelle
def get_config():
    """Renvoie la configuration selon l'environnement défini"""
    env = os.environ.get('FLASK_ENV', 'default')
    return config.get(env)
