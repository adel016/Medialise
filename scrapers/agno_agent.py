# ancien
# from utils.mongo import get_collection

from scrapers.utils.mongo import get_collection


class Agent:
    """
    Agent de base minimal pour les tests.
    Tu peux l'enrichir plus tard (logging, contexte, etc.).
    """
    def __init__(self):
        # Exemple : connexion à la collection MongoDB
        self.medicines = get_collection("medicines")

    def run(self, *args, **kwargs):
        """
        Méthode à surcharger dans les agents spécialisés.
        """
        raise NotImplementedError("La méthode run() doit être implémentée par les sous-classes.")