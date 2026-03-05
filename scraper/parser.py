from bs4 import BeautifulSoup
from datetime import datetime
from typing import List, Dict, Optional
import logging

from .models import Job
from .quality import ExtractionMethod, ExtractionConfidenceCalculator

logger = logging.getLogger(__name__)


def parse_jobs(html: str, search_term: str) -> List[Job]:
    """Extract jobs from search results page"""
    soup = BeautifulSoup(html, "lxml")
    jobs = []
    job_links = soup.find_all("a", class_="gb-results-list__item")

    for link in job_links:
        try:
            title_tag = link.find(["h3", "h2"], class_="gb-results-list__title")
            if not title_tag:
                continue
            
            title = title_tag.find("strong").text.strip() if title_tag.find("strong") else title_tag.text.strip()

            info_section = link.find("div", class_="gb-results-list__info")
            company = None
            if info_section:
                company_tag = info_section.find("strong")
                if company_tag:
                    company = company_tag.text.strip()

            location_tag = link.find("span", class_="location")
            location = location_tag.text.strip() if location_tag else None

            salary_tag = link.find(string=lambda x: x and ("USD" in str(x) or "CLP" in str(x) or "mes" in str(x)))
            salary = salary_tag.strip() if salary_tag else None

            url = link.get("href")
            if not url:
                continue
            
            if not url.startswith("http"):
                url = f"https://www.getonbrd.com{url}"

            job = Job(
                title=title,
                company=company or "Unknown",
                location=location,
                salary=salary,
                url=url,
                description=None,
                search_term=search_term,
                scraped_at=datetime.utcnow()
            )

            jobs.append(job)

        except Exception as e:
            logger.debug(f"Error parsing job link: {e}")
            continue

    return jobs


def parse_job_details(html: str) -> dict:
    """Extract detailed information from individual job posting"""
    soup = BeautifulSoup(html, "lxml")
    
    details = {
        "description": None,
        "description_extraction_method": None,
        "description_confidence": None,
        "skills": None,
        "skills_confidence": None,
        "experience_level": None,
        "contract_type": None,
        "job_category": None
    }

    try:
        # Strategy 1: Search by class containing description keywords
        description_section = soup.find("div", class_=lambda x: x and any(
            keyword in str(x).lower() 
            for keyword in ["description", "job-description", "offer", "content", "post-description", "job-post"]
        ))
        
        if description_section:
            description_text = description_section.get_text(strip=True)
            if len(description_text) > 50:
                details["description"] = description_text
                details["description_extraction_method"] = ExtractionMethod.CLASS_SEARCH.value
                details["description_confidence"] = ExtractionConfidenceCalculator.score_description(
                    description_text, ExtractionMethod.CLASS_SEARCH, len(html)
                )
        
        # Strategy 2: Search long paragraphs
        if not details["description"]:
            paragraphs = soup.find_all("p")
            long_paragraphs = [p.get_text(strip=True) for p in paragraphs if len(p.get_text(strip=True)) > 100]
            if long_paragraphs:
                details["description"] = " ".join(long_paragraphs[:3])
                details["description_extraction_method"] = ExtractionMethod.PARAGRAPHS.value
                details["description_confidence"] = ExtractionConfidenceCalculator.score_description(
                    details["description"], ExtractionMethod.PARAGRAPHS, len(html)
                )
        
        # Strategy 3: Search in article/main tags
        if not details["description"]:
            main_content = soup.find("article") or soup.find("main") or soup.find("div", class_="container")
            if main_content:
                for script in main_content(["script", "style"]):
                    script.decompose()
                text = main_content.get_text(strip=True)
                if len(text) > 100:
                    details["description"] = text[:2000]
                    details["description_extraction_method"] = ExtractionMethod.ARTICLE_TAG.value
                    details["description_confidence"] = ExtractionConfidenceCalculator.score_description(
                        details["description"], ExtractionMethod.ARTICLE_TAG, len(html)
                    )

        # Extract skills
        skills_section = soup.find("div", class_=lambda x: x and any(
            keyword in str(x).lower() 
            for keyword in ["skill", "technology", "tech", "tools", "herramienta"]
        ))
        if skills_section:
            skill_items = skills_section.find_all(["li", "span", "p"])
            skills = [item.get_text(strip=True) for item in skill_items if item.get_text(strip=True)]
            if skills:
                details["skills"] = skills
                details["skills_confidence"] = ExtractionConfidenceCalculator.score_skills(
                    skills, ExtractionMethod.CLASS_SEARCH
                )

        # Extract experience level
        exp_keywords = ["junior", "mid", "middle", "senior", "lead", "principal", "entry", "level"]
        for keyword in exp_keywords:
            if soup.find(string=lambda x: x and keyword.lower() in str(x).lower()):
                details["experience_level"] = keyword.capitalize()
                break

        # Extract contract type
        contract_keywords = {
            "full-time": ["full time", "full-time", "tiempo completo", "jornada completa"],
            "contract": ["contract", "contrato", "freelance", "por proyecto"],
            "part-time": ["part time", "part-time", "tiempo parcial"],
            "temporary": ["temporary", "temporal"]
        }
        for contract_type, keywords in contract_keywords.items():
            for keyword in keywords:
                if soup.find(string=lambda x: x and keyword.lower() in str(x).lower()):
                    details["contract_type"] = contract_type
                    break
            if details["contract_type"]:
                break

        # Extract job category
        category_keywords = {
            "Backend": ["backend", "back-end"],
            "Frontend": ["frontend", "front-end"],
            "Full Stack": ["full stack", "fullstack"],
            "Data Engineering": ["data engineer", "etl", "data pipeline"],
            "Data Science": ["data science", "machine learning", "ml"],
            "DevOps": ["devops", "dev-ops"],
            "Cloud": ["cloud architect", "aws", "gcp", "azure"],
            "Analytics": ["analytics", "data analyst", "bi"]
        }
        for category, keywords in category_keywords.items():
            for keyword in keywords:
                if soup.find(string=lambda x: x and keyword.lower() in str(x).lower()):
                    details["job_category"] = category
                    break
            if details["job_category"]:
                break

    except Exception as e:
        logger.error(f"Error parsing job details: {e}")

    return details
