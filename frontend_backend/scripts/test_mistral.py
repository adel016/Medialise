import os
import sys
import logging
from dotenv import load_dotenv
from mistralai import Mistral

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Add parent directory to path so we can import from the project
sys.path.append('..')

def test_mistral_api():
    """Simple test script to verify Mistral API connection"""
    # Load environment variables
    load_dotenv()
    
    # Get the API key
    api_key = os.getenv('MISTRAL_API_KEY')
    if not api_key:
        logger.error("No API key found. Make sure MISTRAL_API_KEY is set in your .env file")
        return False
    
    logger.info(f"API key loaded: {api_key[:5]}...{api_key[-5:]}")
    
    try:
        # Initialize Mistral client
        client = Mistral(api_key=api_key)
        
        # Make a simple test query
        logger.info("Sending test request to Mistral API...")
        chat_response = client.chat.complete(
            model="mistral-small-latest",
            messages=[
                {
                    "role": "user",
                    "content": "Bonjour, qui es-tu?"
                }
            ]
        )
        
        # Check if we got a valid response
        logger.info(f"Response received: {chat_response.choices[0].message.content[:100]}...")
        
        # If we reach here, the API is working
        logger.info("✅ API test successful!")
        return True
        
    except Exception as e:
        logger.error(f"❌ API test failed: {e}")
        return False

if __name__ == "__main__":
    test_mistral_api()

