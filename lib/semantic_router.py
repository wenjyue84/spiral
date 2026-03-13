# lib/semantic_router.py
import json
from sentence_transformers import SentenceTransformer, util
import torch

class SemanticRouter:
    def __init__(self, model_name='all-MiniLM-L6-v2'):
        self.model = SentenceTransformer(model_name)
        self.routes = {}

    def add_route(self, name, examples):
        """
        Adds a route with a list of example phrases.
        """
        self.routes[name] = {
            "examples": examples,
            "embeddings": self.model.encode(examples, convert_to_tensor=True)
        }

    def route(self, text, threshold=0.5):
        """
        Routes a given text to the best matching route.
        """
        if not self.routes:
            return None

        text_embedding = self.model.encode(text, convert_to_tensor=True)

        best_score = -1
        best_route = None

        for name, route_data in self.routes.items():
            cos_scores = util.pytorch_cos_sim(text_embedding, route_data["embeddings"])[0]
            top_score, _ = torch.max(cos_scores, dim=0)

            if top_score > best_score:
                best_score = top_score
                best_route = name

        if best_score > threshold:
            return best_route
        return None

def create_complexity_router():
    """
    Creates a router pre-configured for 'simple' and 'complex' story classification.
    """
    router = SemanticRouter()
    router.add_route(
        name="complex",
        examples=[
            "Refactor the authentication system to use JWT",
            "Implement a new caching layer for the database",
            "Integrate with a third-party payment gateway",
            "Develop a real-time notification system",
            "Create a new microservice for user profiles"
        ]
    )
    router.add_route(
        name="simple",
        examples=[
            "Fix a typo on the login page",
            "Change the color of the primary button",
            "Add a new field to the user profile page",
            "Update the terms of service link",
            "Improve the error message for invalid login"
        ]
    )
    return router
