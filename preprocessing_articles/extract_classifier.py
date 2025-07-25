"""
Script to classify the tags, subsector, tickers, and sentiment of the news article
"""

from langchain.prompts              import PromptTemplate
from langchain_core.output_parsers  import JsonOutputParser
from langchain_core.runnables       import RunnableParallel
from operator                       import itemgetter
from supabase                       import create_client, Client

from llm_models.get_models  import LLMCollection, invoke_llm_async
from llm_models.llm_prompts import (ClassifierPrompts, 
                                    TagsClassification, 
                                    TickersClassification, 
                                    SubsectorClassification, 
                                    SentimentClassification, 
                                    DimensionClassification)

from config.setup           import LOGGER, SUPABASE_URL, SUPABASE_KEY

import json
import asyncio
from datetime import datetime
from typing import List, Dict, Optional, Union, Tuple
from groq import RateLimitError
import re 

class NewsClassifier:
    """
    A class to handle news article classification including tags, subsectors, tickers, and sentiment.
    """

    def __init__(self):
        """Initialize the NewsClassifier with required dependencies."""
        # Supabase setup
        self.supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

        # LLM setup
        self.llm_collection = LLMCollection()

        # Cache for loaded data
        self._subsectors_cache: Optional[Dict[str, str]] = None
        self._tags_cache: Optional[List[str]] = None
        self._company_cache: Optional[Dict[str, Dict[str, str]]] = None
        self._prompts_cache: Optional[Dict] = None

        # Classifier prompts
        self.prompts = ClassifierPrompts()

    def _load_subsector_data(self) -> Dict[str, str]:
        """
        Load subsector data from Supabase or cache.

        Returns:
            Dict[str, str]: Dictionary mapping subsector slugs to descriptions
        """
        if self._subsectors_cache is not None:
            return self._subsectors_cache

        if datetime.today().day in [1, 15]:
            response = (
                self.supabase.table("idx_subsector_metadata")
                .select("slug, description")
                .execute()
            )

            subsectors = {row["slug"]: row["description"] for row in response.data}

            with open("./data/subsectors_data.json", "w") as f:
                json.dump(subsectors, f)
        else:
            with open("./data/subsectors_data.json", "r") as f:
                subsectors = json.load(f)

        self._subsectors_cache = subsectors
        return subsectors

    def _load_tag_data(self) -> List[str]:
        """
        Load tag data from JSON file.

        Returns:
            List[str]: List of available tags
        """
        if self._tags_cache is not None:
            return self._tags_cache

        with open("./data/unique_tags.json", "r") as f:
            tags = json.load(f)

        self._tags_cache = tags
        return tags

    def _load_company_data(self) -> Dict[str, Dict[str, str]]:
        """
        Load company data from Supabase or cache.

        Returns:
            Dict[str, Dict[str, str]]: Dictionary mapping company symbols to their details
        """
        if self._company_cache is not None:
            return self._company_cache

        if datetime.today().day in [1, 15]:
            response = (
                self.supabase.table("idx_company_profile")
                .select("symbol, company_name, sub_sector_id")
                .execute()
            )

            subsector_response = (
                self.supabase.table("idx_subsector_metadata")
                .select("sub_sector_id, sub_sector")
                .execute()
            )

            subsector_data = {
                row["sub_sector_id"]: row["sub_sector"]
                for row in subsector_response.data
            }

            company = {}
            for row in response.data:
                company[row["symbol"]] = {
                    "symbol": row["symbol"],
                    "name": row["company_name"],
                    "sub_sector": subsector_data[row["sub_sector_id"]],
                }

            for attr in company:
                company[attr]["sub_sector"] = (
                    company[attr]["sub_sector"]
                    .replace("&", "")
                    .replace(",", "")
                    .replace("  ", " ")
                    .replace(" ", "-")
                    .lower()
                )

            with open("./data/companies.json", "w") as f:
                json.dump(company, f, indent=2)
        else:
            with open("./data/companies.json", "r") as f:
                company = json.load(f)

        self._company_cache = company
        return company

    async def _classify_openai_async(
        self, body: str, category: str, title: str = ""
    ) -> Union[List[str], str]:
        """
        Asynchronously classify text using LLM based on the specified category.

        Args:
            body (str): Text to classify
            category (str): Category to classify into (tags, tickers, subsectors, sentiment, dimension)
            title (str): Article title (required for dimension category)

        Returns:
            Union[List[str], str]: Classification results
        """
        # Prompt template mapping
        prompt_methods = {
            "tags": self.prompts.get_tags_prompt(),
            "tickers": self.prompts.get_tickers_prompt(),
            "subsectors": self.prompts.get_subsectors_prompt(),
            "sentiment": self.prompts.get_sentiment_prompt(),
            "dimension": self.prompts.get_dimension_prompt()
        }

        # Load tag data
        tags = self._load_tag_data()

        # Load company data 
        company = self._load_company_data()
        
        # Load subsector data
        subsectors = self._load_subsector_data()

        # Pydantic mapping 
        model_mapping = {
            "tags": TagsClassification,
            "tickers": TickersClassification,
            "subsectors": SubsectorClassification,
            "sentiment": SentimentClassification,
            "dimension": DimensionClassification
        }

        # Create Parser
        classifier_parser = JsonOutputParser(pydantic_object=model_mapping.get(category))
        
        # Get prompt template
        template = prompt_methods.get(category)

        # Get input variables based on category
        if category.lower() == 'dimension':
            input_variables = ["title", "body"]
        else:
            input_variables = ['body']

        # Create prompt with input variables and format instructions
        prompt = PromptTemplate(
            template=template, 
            input_variables=input_variables,
            partial_variables={
                "format_instructions": classifier_parser.get_format_instructions()
            }
        )

        # Add category-specific data to prompt
        if category == "tags":
            prompt = prompt.partial(tags=", ".join(tags))
        elif category == "tickers":
            prompt = prompt.partial(tickers=", ".join(company.keys()))
        elif category == "subsectors":
            prompt = prompt.partial(subsectors=", ".join(subsectors.keys()))

        # Create runnable system based on category
        if category == "dimension":
            runnable_system = RunnableParallel({
                "title": itemgetter("title"),
                "body": itemgetter("body")
            })
        else:
            runnable_system = RunnableParallel({
                "body": itemgetter("body")
            })
        
        # Prepare input data
        input_data = {"title": title, "body": body}

        for llm in self.llm_collection.get_llms():
            try:
                # Create chain with current LLM
                classifier_chain = (
                    runnable_system
                    | prompt 
                    | llm 
                    | classifier_parser
                )

                # Process with current LLM
                result = await invoke_llm_async(classifier_chain, input_data)
    
                # Sleep 8s
                await asyncio.sleep(8)

                if result is None : 
                    LOGGER.warning(f"API call failed for category: {category}. trying next LLM.")
                    continue 

                # Return based on category type
                if category == "tags":
                    result_output = result.get("tags", [])
                    seen = set()
                    check_tags = []
                    for tag in result_output: 
                        if tag in tags and tag not in seen:
                            seen.add(tag)
                            check_tags.append(tag) 
                    return check_tags
                elif category == "tickers":
                    return result.get("tickers", [])
                elif category == "subsectors":
                    return result.get("subsector", "")
                elif category == "sentiment":
                    return result.get("sentiment", "")
                elif category == "dimension":
                    # For dimension, return the entire dict or extract specific fields
                    if isinstance(result, dict):
                        return result
                    else:
                        # Fallback if result is not a dict
                        return {
                            "valuation": result.get("valuation", None),
                            "future": result.get("future", None),
                            "technical": result.get("technical", None),
                            "financials": result.get("financials", None),
                            "dividend": result.get("dividend", None),
                            "management": result.get("management", None),
                            "ownership": result.get("ownership", None),
                            "sustainability": result.get("sustainability", None),
                        }
            
            except RateLimitError as error:
                error_message = str(error).lower()
                if "tokens per day" in error_message or "tpd" in error_message:
                    LOGGER.warning(f"LLM: {llm.model_name} hit its daily token limit. Moving to next LLM.")
                    continue 

            except json.JSONDecodeError as error:
                LOGGER.error(f"[ERROR] LLM Failed classified returned malformed JSON: {error}")
                continue

            except Exception as error:
                LOGGER.error(f"[ERROR] LLM failed classified with error: {error}")
                continue
            
        # Return appropriate default if all LLMs fail
        LOGGER.error(f"All LLMs failed for category '{category}'.")
        return None

    async def classify_article_async(
        self, title: str, body: str
    ) -> Tuple[List[str], List[str], str, str, Dict[str, Optional[int]]]:
        """
        Asynchronously classify an article's tags, tickers, subsector, sentiment, and dimensions.

        Args:
            title (str): Article title
            body (str): Article content

        Returns:
            Tuple[List[str], List[str], str, str, Dict[str, Optional[int]]]:
                (tags, tickers, subsector, sentiment, dimensions)
        """
        # Llama groq sensitive to ratelimit, so decied to not use .gather but sequential instead
        tags = await self._classify_openai_async(body, "tags", title)
        tickers = await self._classify_openai_async(body, "tickers", title)  
        subsector = await self._classify_openai_async(body, "subsectors", title)
        sentiment = await self._classify_openai_async(body, "sentiment", title)
        dimension = await self._classify_openai_async(body, "dimension", title)

        # Check for ANY failure: either an unexpected Exception OR None signal
        results = [tags, tickers, subsector, sentiment, dimension]
        if any(isinstance(res, Exception) or res is None for res in results):
            LOGGER.error("One or more classification steps failed. Failing entire article classification.")
            return None

        return tags, tickers, subsector, sentiment, dimension


# Create a singleton instance
CLASSIFIER = NewsClassifier()

# Backward compatibility functions
def load_company_data() -> Dict[str, Dict[str, str]]:
    """
    Load company data from Supabase or cache.

    Returns:
        Dict[str, Dict[str, str]]: Dictionary mapping company symbols to their details.
    """
    return CLASSIFIER._load_company_data()