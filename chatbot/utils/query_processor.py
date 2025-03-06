import os
import json
import pickle
import numpy as np
import faiss
from django.db.models import Sum, Avg, Min, Max, Count
import matplotlib.pyplot as plt
import openai
import django
from sentence_transformers import SentenceTransformer
from chatbot.utils.faiss_utils import ensure_cached, _local_path
from django.conf import settings



# Path to FAISS indexes
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # now points to /chatbot

def read_prompt_from_file(filename):
    """
    Read a prompt from a text file
    """
    try:
        file_path = os.path.join(BASE_DIR, 'data', filename) # Uses data folder to read the txt file
        with open(file_path, 'r') as file: 
            return file.read().strip()
    except FileNotFoundError:
        print(f"Error: {filename} not found. Using default prompt.")
        return None
    except Exception as e:
        print(f"Error reading {filename}: {e}")
        return None
        

def format_results_with_gpt(user_query, raw_result):
    """
    Format the raw execution results using ChatGPT to make them more presentable
    
    Parameters:
    user_query (str): The original query from the user
    raw_result (any): The raw result from code execution
    openai_client: The OpenAI client instance
    
    Returns:
    str: A user-friendly, formatted response
    """
    try:
        # Convert complex data types to strings if needed
        if not isinstance(raw_result, str):
            import json
            try:
                # Try to convert to JSON if it's a complex data structure
                result_str = json.dumps(raw_result, indent=2, default=str)
            except (TypeError, ValueError):
                # If JSON conversion fails, use simple string representation
                result_str = str(raw_result)
        else:
            result_str = raw_result
            
        # Prepare the prompt for GPT
        system_prompt = (
            "You are an AI assistant that helps users understand data from their receipts. "
            "Your task is to take the raw results of a database query and format them in a clear, "
            "conversational way that directly answers the user's question. "
            "Make the response sound natural and helpful. "
            "Please keep the answer objective. If the user asks for subjective answer such as opinions or comments. Please ignore and just provide the objective answer"
            "Only make the result sound human readable, do not provide more information"
            "Keep your response concise and focused on what the user asked."
        )
        
        # Create the user message with both the query and the result
        user_message = (
            f"Here is the user's original query: \"{user_query}\"\n\n"
            f"And here is the raw result from our database:\n{result_str}\n\n"
            "Please format this as a clear, helpful response that answers their question."
        )
        
        # Call the OpenAI API
        response = openai.chat.completions.create(
            model="gpt-4o",  # Using the same model as in extract_search_terms
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message}
            ]
        )
        
        # Extract and return the formatted response
        formatted_result = response.choices[0].message.content
        return formatted_result
        
    except Exception as e:
        # Fall back to the original result if something goes wrong
        print(f"Error in format_results_with_gpt: {e}")
        return f"Result: {raw_result}"

def load_faiss_indexes():
    """
    Ensure the three FAISS indexes are cached locally, then load them
    into memory and return a dict shaped like:
        {
            "company": {"index": <faiss.Index>, "mapping": {int: str}},
            "address": {"index": <faiss.Index>, "mapping": {int: str}},
            "item":    {"index": <faiss.Index>, "mapping": {int: str}},
        }
    Any index that fails to download/read is silently skipped.
    """
    results = {}
    for kind in ("company", "address", "item_description"):
        try:
            # 1. Make sure the *.faiss file is present in FAISS_CACHE_DIR
            ensure_cached(kind)

            # 2. Load index and mapping
            idx_path = _local_path(kind)
            idx = faiss.read_index(str(idx_path))
            with open(idx_path.with_suffix(".pkl"), "rb") as fh:
                mapping = pickle.load(fh)

            # 3. Store in results dict (rename key "item_description"→"item")
            key = "item" if kind == "item_description" else kind
            results[key] = {"index": idx, "mapping": mapping}

        except Exception as e:
            # Log and continue; the chatbot can still operate with partial data
            print(f"[FAISS] {kind} index unavailable: {e}")

    return results
        
def detect_malicious_intent(user_query):
    try:
        system_prompt = read_prompt_from_file('malicious_intent_prompt.txt')
        if system_prompt is None:  # fallback
            system_prompt = (
                "Return JSON {\"malicious\": bool, \"reason\": str} telling whether the "
                "request below could harm data integrity, privacy or availability."
            )

        response = openai.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_query}
            ],
            response_format={"type": "json_object"}
        )

        verdict = json.loads(response.choices[0].message.content)
        return verdict.get("malicious", False), verdict.get("reason", "")
    except Exception as e:
        # Fail-closed: treat as malicious but keep the API contract
        print(f"Malicious-intent detector error: {e}")
        return True, "internal detector error"


def extract_search_terms(user_query):
    """
    Agent 1: Ask GPT to extract search terms from the user query
    """
    try:
        # Read the prompt from file
        system_prompt = read_prompt_from_file('extract_search_terms_prompt.txt')
        if system_prompt is None:
            system_prompt = (
                "Your task is to analyze a user query about receipt data and extract key search terms "
                "that could be used for semantic search. Specifically, extract:"
                "\n1. Company names (e.g., Walmart, Amazon, Starbucks)"
                "\n2. Addresses or location references (e.g., Main Street, New York)"
                "\n3. Item descriptions or product names (e.g., coffee, t-shirt, groceries)"
                "\n\nRETURN EXACTLY THIS JSON FORMAT:"
                "\n{"
                '\n  "companies": ["company1", "company2", ...], '
                '\n  "addresses": ["address1", "address2", ...], '
                '\n  "items": ["item1", "item2", ...]'
                "\n}"
                "\n\nIf no terms of a certain type are found, include an empty array for that category."
                "\nDO NOT include any additional fields in the JSON."
            )
        
        response = openai.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Extract search terms from this query: {user_query}"}
            ],
            response_format={"type": "json_object"}
        )
        
        extracted_data = json.loads(response.choices[0].message.content)
        
        # Ensure the extracted data has the expected format
        required_keys = ["companies", "addresses", "items"]
        for key in required_keys:
            if key not in extracted_data:
                extracted_data[key] = []
            elif not isinstance(extracted_data[key], list):
                extracted_data[key] = []
        
        return extracted_data
    except Exception as e:
        print(f"Error in extract_search_terms: {e}")
        return {"companies": [], "addresses": [], "items": []}

def search_with_faiss(search_terms, faiss_data, model):
    """
    Search the FAISS indexes using the extracted search terms
    """
    results = {
        "companies": [],
        "addresses": [],
        "items": []
    }
    
    try:
        # Search for companies
        if "companies" in search_terms and search_terms["companies"] and "company" in faiss_data:
            for company_term in search_terms["companies"]:
                # Get embedding for the company term
                company_embedding = model.encode([company_term])
                
                # Search the index
                distances, indices = faiss_data["company"]["index"].search(
                    np.array(company_embedding).astype('float32'), 
                    5  # Top 5 results
                )
                
                # Get the company names from the mapping
                for i, idx in enumerate(indices[0]):
                    if idx in faiss_data["company"]["mapping"]:
                        company = faiss_data["company"]["mapping"][idx]
                        similarity = 1 / (1 + distances[0][i])  # Convert distance to similarity
                        results["companies"].append({
                            "value": company,
                            "similarity": float(similarity)
                        })
        
        # Search for addresses
        if "addresses" in search_terms and search_terms["addresses"] and "address" in faiss_data:
            for address_term in search_terms["addresses"]:
                # Get embedding for the address term
                address_embedding = model.encode([address_term])
                
                # Search the index
                distances, indices = faiss_data["address"]["index"].search(
                    np.array(address_embedding).astype('float32'), 
                    5  # Top 5 results
                )
                
                # Get the addresses from the mapping
                for i, idx in enumerate(indices[0]):
                    if idx in faiss_data["address"]["mapping"]:
                        address = faiss_data["address"]["mapping"][idx]
                        similarity = 1 / (1 + distances[0][i])
                        results["addresses"].append({
                            "value": address,
                            "similarity": float(similarity)
                        })
        
        # Search for items
        if "items" in search_terms and search_terms["items"] and "item" in faiss_data:
            for item_term in search_terms["items"]:
                # Get embedding for the item term
                item_embedding = model.encode([item_term])
                
                # Search the index
                distances, indices = faiss_data["item"]["index"].search(
                    np.array(item_embedding).astype('float32'), 
                    5  # Top 5 results
                )
                
                # Get the item descriptions from the mapping
                for i, idx in enumerate(indices[0]):
                    if idx in faiss_data["item"]["mapping"]:
                        item = faiss_data["item"]["mapping"][idx]
                        similarity = 1 / (1 + distances[0][i])
                        results["items"].append({
                            "value": item,
                            "similarity": float(similarity)
                        })
        
        return results
    except Exception as e:
        print(f"Error in search_with_faiss: {e}")
        return results

def get_executable_code_with_feedback(user_query, models_content, faiss_results, user, max_attempts=3):
    """
    Agent 2: Generate executable code with feedback loop for failed code execution
    """
    attempt = 1
    previous_code = None
    previous_error = None
    chat_history = []
    
    while attempt <= max_attempts:
        try:
            # Prepare a formatted version of the FAISS results for the prompt
            faiss_info = ""
            
            if faiss_results["companies"]:
                faiss_info += "Similar companies found in database:\n"
                for item in faiss_results["companies"]:
                    faiss_info += f"- {item['value']} (similarity: {item['similarity']:.4f})\n"
            
            if faiss_results["addresses"]:
                faiss_info += "\nSimilar addresses found in database:\n"
                for item in faiss_results["addresses"]:
                    faiss_info += f"- {item['value']} (similarity: {item['similarity']:.4f})\n"
            
            if faiss_results["items"]:
                faiss_info += "\nSimilar items found in database:\n"
                for item in faiss_results["items"]:
                    faiss_info += f"- {item['value']} (similarity: {item['similarity']:.4f})\n"
                    
            currentuser = user.id
            
            # Read the prompt from file
            user_prompt = read_prompt_from_file('executable_code_prompt.txt')
            if user_prompt is None:
                user_prompt = (
                    f"Analyze the following query and provide executable Python code that uses Django ORM to answer the query. "
                    f"The user writing the query is user_id={currentuser}. Only use this user's data by filtering with user_id={currentuser}."
                    f"The code should directly use the Django models to get the results.\n\n"
                    f"Query: {user_query}\n\n"
                    f"Models:\n{models_content}\n\n"
                    f"FAISS Semantic Search Results:\n{faiss_info}\n\n"
                    "These semantic search results show the closest matches in our database based on the query. "
                    "For item in the semantic search results, it shows the item moredes field, this field is the {description fieldd in the database} + {categories that chatgpt says this item belongs to}."
                    "First determine if the user query contains a category of items like for example 'groceries' or 'electronics'."
                    "if yes, then make use of the output from faiss for items. This will help determining the items to select if the user query contains a category of items for item like 'groceries' instead of just an item name."
                    "Use this information when constructing your database queries to ensure you're looking for "
                    "the right companies, addresses, or item descriptions that actually exist in the database."
                    "The user could search for example kitchen utensils and if item descriptions could have 'spoon' or 'fork', then these items should be included in code when searching since they are utensils. \n\n"
                    "Return only the Python code without any explanations or markdown formatting. "
                    "The code should be ready to execute and store the result in a variable named 'result'. "
                    "Include all necessary imports and the code should be self-contained. "
                    "The name of the app is 'receipts'. "
                    "Don't have '__name__ == '__main__'' in the code. "
                    "When asked to retrieve image, retrieve image_url from receipts. "
                    "If the query involves exporting data to a file (CSV, Excel, PDF, etc.), the code should include "
                    "the necessary logic to create and save the file. For file operations, use standard Python libraries "
                    "like csv, pandas, or openpyxl as appropriate. "
                    "The file should saved with appropiate name where the python code is ran, so it should be saved automatically. "
                    "If you cannot write code to process this query, simply return the exact string: 'Unable to process query'"
                )
            else:
                # Format the prompt with dynamic content
                user_prompt = user_prompt.format(
                    currentuser=currentuser,
                    user_query=user_query,
                    models_content=models_content,
                    faiss_info=faiss_info
                )
            
            # Add feedback from previous attempt if available
            if previous_error:
                feedback_prompt = (
                    f"Your previous code failed to execute with the following error:\n\n"
                    f"```\n{previous_error}\n```\n\n"
                    f"Here's the code that failed:\n\n"
                    f"```python\n{previous_code}\n```\n\n"
                    f"Please fix the issues and provide corrected code. "
                    f"This is attempt {attempt} of {max_attempts}."
                )
                user_prompt = f"{feedback_prompt}\n\n{user_prompt}"
            
            # Add chat history to messages
            messages = []
            for msg in chat_history:
                messages.append(msg)
                
            # Add current prompt as a new message
            messages.append({"role": "user", "content": user_prompt})
            
            # If it's the first attempt, don't include chat history
            if attempt == 1:
                messages = [{"role": "user", "content": user_prompt}]
            
            response = openai.chat.completions.create(
                model="o1-mini",  # Use o1-mini model as in the original code
                messages=messages
            )
            raw_response = response.choices[0].message.content.strip() # POSTMAN CHANGE (THAR)
            
            # Add the response to chat history
            chat_history.append({"role": "user", "content": user_prompt})
            chat_history.append({"role": "assistant", "content": raw_response})
            
            # Check if the response indicates inability to process the query
            if raw_response == "Unable to process query":
                return raw_response
            
            # Clean up any potential markdown code blocks
            if raw_response.startswith("```python"):
                raw_response = raw_response[10:]
            if raw_response.startswith("```"):
                raw_response = raw_response[3:]
            if raw_response.endswith("```"):
                raw_response = raw_response[:-3]
                
            code_string = raw_response.strip()
            previous_code = code_string
            
            # Try to execute the code
            try:
                result = execute_code(code_string)
                
                # If we're here, the code executed without errors
                if isinstance(result, str) and result.startswith("Error:"):
                    raise Exception(result[7:])  # Remove "Error: " prefix
                
                return code_string
            except Exception as e:
                error_message = str(e)
                previous_error = error_message
                attempt += 1
                
        except Exception as e:
            previous_error = str(e)
            attempt += 1
    
    # If we've exhausted all attempts and still failed
    return previous_code  # Return the last attempt even though it failed

def execute_code(code_string):
    try:
        # Create a local namespace
        local_namespace = {}
        global_namespace = globals().copy()
        
        # Make sure Django's aggregation functions and other utilities are available
        from decimal import Decimal
        from datetime import datetime, timedelta
        global_namespace.update({
            'Sum': Sum,
            'Avg': Avg,
            'Min': Min,
            'Max': Max,
            'Count': Count,
            'plt': plt,
            'Decimal': Decimal,
            'datetime': datetime,
            'timedelta': timedelta
        })
        
        # Make sure common file handling libraries are available
        try:
            import csv
            import pandas as pd
            import openpyxl
            global_namespace.update({
                'csv': csv,
                'pd': pd,
                'openpyxl': openpyxl
            })
        except ImportError as e:
            print(f"Warning: Some file export libraries could not be imported: {e}")
        
        # Execute the code in the local namespace with the enhanced globals
        exec(code_string, global_namespace, local_namespace)
        
        # Case 1: Code returned an in-memory file (BytesIO + filename)
        if 'file_stream' in local_namespace and 'filename' in local_namespace:
            return {
                'type': 'file',
                'stream': local_namespace['file_stream'],
                'filename': local_namespace['filename']
            }
        
        # Case 2: Code returned a regular result
        if 'result' in local_namespace:
            return local_namespace['result']

        return "Code executed successfully, but no result returned"

    except Exception as e:
        print(f"Error executing code: {e}")
        return f"Error: {str(e)}"
