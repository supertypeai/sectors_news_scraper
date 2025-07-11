"""
Script to use LLM for summarizing a news article, uses OpenAI and Groq
"""

from bs4            import BeautifulSoup
from nltk.tokenize  import sent_tokenize, word_tokenize
from goose3         import Goose
from requests       import Response, Session
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser
from pydantic import BaseModel

from llm_models.get_models  import LLMCollection

import dotenv
import requests
import os
import re
import nltk
import openai 

dotenv.load_dotenv()
# NLTK download
nltk.data.path.append("./nltk_data")


USER_AGENT = "Mozilla/5.0 (Linux; Android 6.0; Nexus 5 Build/MRA58N) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Mobile Safari/537.36"
HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "*/*",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Cache-Control": "max-age=0",
    "x-test": "true",
}

class NewsOutput(BaseModel):
    title: str
    body: str

# Model Creation
llmcollection = LLMCollection()

def summarize_llama(body):
    # Define JSON schema for output
    json_parser = JsonOutputParser(pydantic_object=NewsOutput)

    # Create a combined prompt template
    prompt_template = ChatPromptTemplate.from_template(
        """Analyze this news article and provide both a title and summary.
        For the title: Create a one sentence title that is not misleading and gives general understanding.
        For the body: Provide a concise, maximum 2 sentences summary highlighting main points, key events, and financial metrics.
        For company mentions, maintain the format 'Company Name (TICKER)'.

        News: {text}

        {format_instructions}
        """
    )

    # Create chain with the first available LLM
    for llm in llmcollection.get_llms():
        try:
            chain = prompt_template | llm | json_parser
            response = chain.invoke(
                {
                    "text": body,
                    "format_instructions": json_parser.get_format_instructions(),
                }
            )

            # Ensure we have both title and body
            if not response.get("title") or not response.get("body"):
                print("[ERROR] LLM returned incomplete response")
                continue

            return response
        
        except openai.RateLimitError as limit:
            # Re-raise the error so the main loop can handle it
            raise limit

        except Exception as e:
            print(f"[ERROR] LLM failed with error: {e}")
            continue

    # If all LLMs fail, return empty strings
    return {"title": "", "body": ""}

def preprocess_text(news_text: str) -> str:
    # Remove parenthesis
    news_text = re.sub(r"\(.*?\)", "", news_text)

    # Tokenize into sentences
    sentences = sent_tokenize(news_text)

    # Tokenize into words, remove stopwords, and convert to lowercase
    stop_words = {
        "a",
        "an",
        "the",
        "with",
        "of",
        "to",
        "and",
        "in",
        "on",
        "for",
        "as",
        "by",
    }
    words = [word_tokenize(sentence) for sentence in sentences]
    words = [
        [word.lower() for word in sentence if word.lower() not in stop_words]
        for sentence in words
    ]

    # Combine words back into sentences
    processed_sentences = [" ".join(sentence) for sentence in words]

    # Combine sentences back into a single string
    processed_text = " ".join(processed_sentences)

    # Remove spaces before punctuation
    processed_text = re.sub(r'\s+([?.!,"])', r"\1", processed_text)
    # Remove multiple spaces
    processed_text = re.sub(r"\s+", " ", processed_text)

    return processed_text


def get_article_body(url: str):
    try:
        proxy = os.environ.get("PROXY_KEY")
        proxy_support = {"http": proxy, "https": proxy}

        session = Session()
        session.proxies.update(proxy_support)
        session.headers.update(HEADERS)

        # g = Goose({'http_proxies': proxy_support, 'https_proxies': proxy_support})
        g = Goose({"http_session": session})
        article = g.extract(url=url)
        print(f"[SUCCESS] Article from url {url} inferenced")
        # print("cleaned text", article.cleaned_text)

        if article.cleaned_text:
            return article.cleaned_text
        else:
            # If fail, get the HTML and extract the text
            print("[REQUEST FAIL] Goose3 returned empty string, trying with soup")
            response: Response = requests.get(url)
            response.raise_for_status()

            soup: BeautifulSoup = BeautifulSoup(response.content, "html.parser")
            content: BeautifulSoup = soup.find("div", class_="content")
            print(f"[SUCCESS] Article inferenced from url {url} using soup")
            return content.get_text()
        
    except Exception as error:
        print(
            f"[PROXY FAIL] Goose3 failed with error, trying with no proxy: {error} to url {url}"
        )
        try:
            g = Goose()
            article = g.extract(url=url)
            return article.cleaned_text
        except Exception as error:
            print(f"[ERROR] Goose3 failed with error: {error}")
            return ""


def summarize_news(url: str) -> tuple[str, str]:
    news_text = get_article_body(url)
    if len(news_text) > 0:
        news_text = preprocess_text(news_text)
        response = summarize_llama(news_text)

        return response["title"], response["body"]
    else:
        return "", ""


# urls = [
#     "https://www.idnfinancials.com/news/50366/boosting-growth-tpma-acquires-worth-us",
#     "https://www.idnfinancials.com/news/50438/consistent-profit-dividend-ptba-rakes-indeks-categories",
#     "https://www.idnfinancials.com/news/50433/smdr-listed-dividend-category-indeks-tempo-idnfinancials",
#     "https://www.idnfinancials.com/news/50431/declining-market-cap-sido-listed-categories-indeks"
# ]

# for url in urls:
#     title, body = summarize_news(url)
#     print(title)
#     print(body)