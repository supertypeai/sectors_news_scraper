"""
Script to generate the score of news articles.

Provides comprehensive scoring based on multiple criteria including:
- Timeliness and source credibility
- Clarity, structure, and relevance to Indonesia Stock Market
- Depth of analysis and financial data inclusion
- Market impact and forward-looking statements
- Bonus criteria for high-quality news
"""

from langchain_core.runnables       import RunnableParallel
from operator                       import itemgetter
from langchain.prompts              import PromptTemplate
from langchain_core.output_parsers  import JsonOutputParser

from llm_models.get_models  import LLMCollection, invoke_llm
from llm_models.llm_prompts import ScoringNews, ClassifierPrompts
from config.setup           import LOGGER

from datetime       import datetime
from typing         import Optional
from urllib.parse   import urlparse
import openai 
import json 


class ArticleScorer:
    """
    Enhanced article scorer with robust error handling and configurable criteria.
    """
    def __init__(self):
        """
        Initialize the article scorer.
        """
        self.llm_collection = LLMCollection()
        self._criteria_cache: Optional[str] = None

        # Classifier prompts
        self.prompts = ClassifierPrompts()

    def _get_default_criteria(self) -> str:
        """
        Get default scoring criteria.

        Returns:
            str: Default scoring criteria for news articles.
        """
        return """
            News Article Scoring Criteria (0-100). 

            1. Timeliness (0-10)
            Keywords: "recent", "today", "this week", "Q3 2024", "latest market movement".
            Instructions:

            Score 0-2: Article is outdated (e.g., more than 2 weeks old) and does not reflect current market conditions.
            Score 3-5: Article is somewhat recent (published within the last 2 weeks) but may not be directly tied to current market movements.
            Score 6-8: Article is published within the last week and covers recent developments related to the Indonesia Stock Market.
            Score 9-10: Article is very recent (published within the last 24-48 hours) and is highly relevant to ongoing market conditions.

            2. Source Credibility (0-10)
            Keywords: "Bloomberg", "Reuters", "Kontan", "Bisnis Indonesia", "IDX", "OJK".
            Instructions:

            Score 0-2: Article is from an unknown or unreliable source with no established credibility.
            Score 3-5: Article is from a moderately credible source, such as a regional news outlet or less-known publication.
            Score 6-8: Article is from a well-established national news outlet in Indonesia with some authority in financial reporting.
            Score 9-10: Article is from a top-tier, highly credible source with a strong reputation in financial markets (e.g., Bloomberg, IDX official reports).

            3. Clarity and Structure (0-10)
            Keywords: "clear headline", "well-structured", "organized", "informative lead".
            Instructions:

            Score 0-2: Article is poorly structured, with unclear headlines and a confusing body.
            Score 3-5: Article is somewhat organized but lacks clarity in its lead or body.
            Score 6-8: Article is well-organized, with a clear headline and body that is easy to follow.
            Score 9-10: Article is excellently structured, with a highly informative headline, lead, and logically organized body that enhances readability.

            4. Relevance to the Indonesia Stock Market (0-15)
            Keywords: "IDX", "JCI", "Jakarta Composite Index", "Indonesian companies", "OJK regulations".
            Instructions:

            Score 0-5: Article has little to no relevance to the IDX or the Indonesian stock market, or it is only tangentially related.
            Score 6-10: Article discusses some relevant aspects of the Indonesian market, such as general market movements or non-specific company events.
            Score 11-15: Article is directly relevant to key drivers of the Indonesian stock market, including specific IDX-listed companies, regulatory changes, or major sector developments.

            5. Depth of Analysis (0-15)
            Keywords: "detailed analysis", "market data", "earnings report", "sector outlook".
            Instructions:

            Score 0-5: Article provides only superficial coverage, with little to no analysis or data.
            Score 6-10: Article includes some level of analysis, such as basic data or expert opinions, but lacks depth.
            Score 11-15: Article offers a comprehensive analysis with detailed data, expert insights, and thorough exploration of market implications, particularly for the Indonesian market.

            6. Financial Data Inclusion (0-10)
            Keywords: "earnings", "stock price", "P/E ratio", "ROE", "dividends".
            Instructions:

            Score 0-2: Article includes no financial data relevant to the Indonesian market.
            Score 3-5: Article includes basic financial data, such as stock prices or general market indices, with limited context.
            Score 6-8: Article includes detailed financial metrics, such as earnings, ratios, or dividends, with some analysis.
            Score 9-10: Article is rich in relevant financial data, providing extensive metrics and detailed analysis specific to Indonesian companies or sectors.

            7. Balanced Reporting (0-5)
            Keywords: "balanced view", "multiple perspectives", "neutral tone", "pros and cons".
            Instructions:

            Score 0-1: Article is highly biased, presenting a one-sided view without acknowledging alternative perspectives.
            Score 2-3: Article attempts some balance but is still somewhat skewed or lacks depth in presenting multiple viewpoints.
            Score 4-5: Article is well-balanced, presenting multiple perspectives and a neutral tone, offering a comprehensive view of the topic.

            8. Sector and Industry Focus (0-10)
            Keywords: "banking sector", "telecom industry", "consumer goods", "mining", "energy", "manufacturing".
            Instructions:

            Score 0-2: Article lacks any clear sector or industry focus relevant to Indonesia.
            Score 3-5: Article discusses sectors or industries in general terms without specificity.
            Score 6-8: Article provides a focused discussion on a specific sector or industry relevant to the Indonesian market.
            Score 9-10: Article is highly specific, with in-depth coverage of key sectors or industries, offering detailed insights into Indonesian market trends.

            9. Market Impact Relevance (0-10)
            Keywords: "market movement", "investor sentiment", "stock price impact", "IDX fluctuations".
            Instructions:

            Score 0-2: Article does not discuss or predict any market impact.
            Score 3-5: Article mentions potential market impacts but lacks detail or analysis.
            Score 6-8: Article discusses market impacts with a reasonable degree of detail, including potential effects on stock prices or investor sentiment.
            Score 9-10: Article clearly outlines both immediate and long-term market impacts, with detailed analysis of how news might influence the IDX or specific stocks.

            10. Forward-Looking Statements (0-10)
            Keywords: "future outlook", "market trend", "forecast", "projections", "strategic move".
            Instructions:

            Score 0-2: Article contains no forward-looking statements or projections.
            Score 3-5: Article offers basic projections or trends but lacks depth.
            Score 6-8: Article provides well-informed short-term and some long-term projections relevant to the Indonesian market.
            Score 9-10: Article includes detailed and insightful projections, offering a clear outlook for both short-term and long-term market developments in Indonesia.

            Bonus Criteria for High-Quality News (Additional Points)

            1. Primary CTA (Up to 5 Points Each):
            - Does the article mention any of the following?
                - Dividend rate + cum date (+5 points)
                - Policy/Bill Passing (especially if it's eyeball-catching) (+5 points)
                - Insider trading (especially if it's eyeball-catching) (+5 points)
                - Acquisition/Merging (+5 points)
                - Launching of a new company business plan (new project/income source/new partner/new contract) (+5 points)
                - Earnings Report (+5 points)

            2. Secondary CTA (Up to 2 Points Each):
            - Does the article mention any of the following?
                - IDX performance against the US market (+2 points)
                - Rupiah performance (+2 points)
                - Net foreign buy and sell (+2 points)
                - Recommended stocks (stock watchlist) (+2 points)
                - Global commodities prices (+2 points)

            Total Score:
            - Base Score: Up to 100 points based on the 10 main criteria.
            - Bonus Score: Additional points based on Primary and Secondary CTA criteria.

            Standard Scores for Example Articles. 
            The final score can be any number in range 0 and 100.
                0 Score: The article is outdated, from an unknown source, poorly structured, has no relevance to the IDX, lacks analysis, financial data, or any market impact, and does not mention any CTA. Example: "Some company in Asia made a move."
                25 Score: The article is from a moderately credible source, somewhat recent, with basic relevance to the IDX but lacks depth, analysis, or financial data. It's somewhat organized but still vague. Example: "PT X acquired 20% of PT Y."
                50 Score: The article is recent, from a credible source, somewhat relevant to the IDX, provides basic analysis and financial data, and has a moderate impact on the market. It is organized and mentions some sector focus. Example: "PT X acquired 55% of PT Y, affecting the IDX slightly."
                75 Score: The article is very recent, from a top-tier source, highly relevant to the IDX, offers detailed analysis, includes extensive financial data, and has a significant market impact. It is well-organized, balanced, and focuses on key sectors. Example: "PT X acquired 55% of PT Y, which is expected to significantly impact the IDX and the mining sector."
                80 Score: The article includes the above qualities plus mentions a Primary CTA like a new business plan, earnings report, or acquisition. It's relevant, well-structured, with clear forward-looking statements. Example: "PT X's acquisition of PT Y and their new strategic partnership is expected to double their earnings next quarter."
                90 Score: The article is highly detailed, with extensive analysis, financial data, balanced reporting, and multiple Primary CTAs like dividends, acquisitions, and earnings reports. Example: "PT X's acquisition of PT Y, coupled with their new dividend policy, is expected to significantly boost their stock price and impact the IDX."
                95 Score: The article includes all the above qualities, with additional insight into long-term market impacts, multiple sector focuses, and comprehensive forward-looking statements. Example: "PT X's strategic acquisition and upcoming merger, along with their new dividend policy, are projected to drive long-term growth in the Indonesian market."
                100 Score: The article is from a top-tier source, published within the last 24 hours, covers multiple Primary and Secondary CTAs, offers in-depth analysis with detailed financial metrics, balanced reporting, comprehensive forward-looking statements, and discusses immediate and long-term market impacts. Example: "PT X's acquisition of PT Y, insider trading activities, new strategic projects, and a 20% increase in dividends, will likely lead to a significant uptick in the IDX over the next year.
                        
            A high quality news article is one that is:
            1. actionable
            2. commercially valuable (request for proposal on a new coal site)
            3. big movement of money (merger and acquisitions, large insider purchase etc)
            4. potential big changes for market cap in the industry
            """
    
    def _extract_domain_urlparse(self, url:str):
        """
        Extract domain from URL using urllib.parse (more robust)
        
        Args:
            url (str): Input URL
            
        Returns:
            str: Domain name or None if invalid
        """
        try:
            parsed = urlparse(url)
            return parsed.netloc
        except:
            return None

    def get_article_score(self, body: str, article_date: str, source: str) -> int:
        """
        Calculate the score for a news article based on comprehensive criteria.

        Args:
            body (str): The article content to score
            article_date (str): The date of the article in ISO format (YYYY-MM-DD).

        Returns:
            int: Score between 0 and 100 (or higher with bonus points)
        """
        # Get the scoring prompt template
        template = self.prompts.get_scoring_prompt()
        
        # Create a scoring parser using the JsonOutputParser
        scoring_parser = JsonOutputParser(pydantic_object=ScoringNews)
        # Prepare the scoring prompt with the template and format instructions
        scoring_prompt = PromptTemplate(
            template = template, 
            input_variables=[
                "criteria",
                "body",
                "source",
                "article_date", 
                "current_datetime"
            ],
            partial_variables={
                "format_instructions": scoring_parser.get_format_instructions()
            }
        )

        # Prepare the scoring system that will handle the article input
        runnable_scoring_system = RunnableParallel(
            {   
                "criteria": itemgetter("criteria"),
                "body": itemgetter("body"),
                "source": itemgetter("source"),
                "article_date": itemgetter("article_date"),
                "current_datetime": lambda _: datetime.now()
            }
        )

        # Prepare the input data for the LLM
        extract_domain = self._extract_domain_urlparse(source)
        input_data = {"criteria":self._get_default_criteria(), 
                      "body":body, 
                      "source":extract_domain,
                      "article_date":article_date}

        for llm in self.llm_collection.get_llms():
            try:
                # Create a scoring chain that combines the system, prompt, and LLM
                scoring_chain = (
                        runnable_scoring_system
                        | scoring_prompt
                        | llm
                        | scoring_parser
                    )
                
                # Process with current LLM
                result_score_raw = invoke_llm(scoring_chain, input_data)

                # If the wrapper signaled a permanent API failure, just try the next LLM.
                if result_score_raw is None:
                    LOGGER.warning("API call failed after all retries, trying next LLM...")
                    continue

                result_score = result_score_raw.get('score', 0)

                if 0 <= result_score <= 150:
                    return result_score
                else: 
                    LOGGER.warning(
                        f"Score out of range: {result_score}, capping at valid range"
                    )
                    return max(0, min(150, result_score))

            except json.JSONDecodeError as error:
                LOGGER.error(f"Failed to parse JSON response: {error}")
                continue

            except Exception as error:
                LOGGER.warning(f"LLM failed with error: {error}")
                continue
        
        return None 

# So we can use the scorer as a singleton
_SCORER = ArticleScorer()

# Backward compatible function
def get_article_score(body: str, article_date: str, source: str):
    """
    Calculate the score for a news article.

    This function maintains backward compatibility with existing code.

    Args:
        body (str): The article content to score

    Returns:
        int: Score between 0 and 100 (or higher with bonus points)
    """
    return _SCORER.get_article_score(body, article_date, source)
