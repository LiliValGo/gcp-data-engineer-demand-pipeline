from bs4 import BeautifulSoup
from datetime import datetime, timezone
from typing import List
import logging
import re

from .models import Job
from .quality import ExtractionMethod, ExtractionConfidenceCalculator

logger = logging.getLogger(__name__)

# Tech keywords for skill extraction
_TECH_KEYWORDS: list[str] = [
    "python", "sql", "spark", "kafka", "airflow", "dbt", "bigquery",
    "redshift", "snowflake", "databricks", "kubernetes", "docker",
    "terraform", "aws", "gcp", "azure", "hadoop", "hive", "presto",
    "flink", "luigi", "prefect", "dagster", "mlflow", "pandas",
    "pyspark", "scala", "java", "go", "rust", "bash", "linux",
    "git", "github", "gitlab", "jenkins", "ci/cd", "datalake",
    "delta lake", "iceberg", "hudi", "tableau", "looker", "power bi",
    "metabase", "grafana", "elasticsearch", "mongodb", "postgresql",
    "mysql", "oracle", "redis", "celery", "fastapi", "flask",
    "react", "fivetran", "stitch", "airbyte", "great expectations",
]
_TECH_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(k) for k in _TECH_KEYWORDS) + r")\b",
    re.IGNORECASE,
)

# Salary patterns - compiled once, reused
_SALARY_PATTERNS = [
    re.compile(r"USD\s*\$?[\d,]+", re.IGNORECASE),
    re.compile(r"CLP\s*\$?[\d,]+", re.IGNORECASE),
    re.compile(r"ARS\s*\$?[\d,]+", re.IGNORECASE),
    re.compile(r"MXN\s*\$?[\d,]+", re.IGNORECASE),
    re.compile(r"BRL\s*R\$?\s*[\d,]+", re.IGNORECASE),
    re.compile(r"PEN\s*S/\s*[\d,]+", re.IGNORECASE),
]


def parse_jobs(html: str, search_term: str) -> List[Job]:
    """Extract jobs from search results page"""
    soup = BeautifulSoup(html, "lxml")
    jobs = []
    # Updated selector: GetOnBoard changed from gb-results-list__item to results-item
    job_links = soup.find_all("a", class_="results-item")

    for link in job_links:
        try:
            # Title is in h4 with class results-list-title
            title_tag = link.find("h4", class_="results-list-title")
            if not title_tag:
                continue

            title = title_tag.find("strong")
            if title:
                title = title.text.strip()
            else:
                title = title_tag.text.strip()
            title = title.replace("Featured job", "").replace("Empleo destacado", "").strip()

            # Company info is in results-list-info section
            info_section = link.find("div", class_="results-list-info")
            company = None
            if info_section:
                strong_tags = info_section.find_all("strong")
                if len(strong_tags) > 1:
                    company = strong_tags[1].text.strip()

            # Location - look for location text (typically after company)
            location = None
            location_parts = []
            for text in info_section.stripped_strings if info_section else []:
                if text and not any(x in text.lower() for x in ["part time", "full time", "remote", "featured", "destacado"]):
                    location_parts.append(text)
                    if len(location_parts) >= 2:
                        break
            location = " ".join(location_parts[-1:]) if location_parts else None

            # Salary - use pre-compiled patterns
            salary_text = link.get_text()
            salary = None
            for pattern in _SALARY_PATTERNS:
                match = pattern.search(salary_text)
                if match:
                    salary = match.group(0)
                    break

            # Job URL
            job_url = link.get("href")
            if not job_url:
                continue

            # Extract skills from description (fallback keyword matching)
            description = link.get_text()
            skills = list(set(_TECH_PATTERN.findall(description)))

            job = Job(
                title=title,
                company=company,
                location=location,
                salary=salary,
                url=job_url,
                description=description[:500] if description else None,
                search_term=search_term,
                skills=skills,
                extraction_method=ExtractionMethod.FALLBACK,
                confidence=0.6,
                scraped_at=datetime.now(timezone.utc),
            )
            jobs.append(job)
            logger.debug(f"Parsed job: {title} at {company}")

        except Exception as e:
            logger.warning(f"Error parsing job link: {e}")
            continue

    logger.info(f"Parsed {len(jobs)} jobs from {search_term}")
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
        # Strategy 1: largest div matching description-related CSS classes
        candidates = soup.find_all("div", class_=lambda x: x and any(
            keyword in str(x).lower()
            for keyword in ["description", "job-description", "offer", "post-description", "job-post", "job-content"]
        ))
        if candidates:
            best = max(candidates, key=lambda d: len(d.get_text(strip=True)))
            description_text = best.get_text(strip=True)
            if len(description_text) > 100:
                details["description"] = description_text
                details["description_extraction_method"] = ExtractionMethod.CLASS_SEARCH.value
                details["description_confidence"] = ExtractionConfidenceCalculator.score_description(
                    description_text, ExtractionMethod.CLASS_SEARCH, len(html)
                )

        # Strategy 2: long paragraphs (join up to 10 paragraphs > 80 chars)
        if not details["description"]:
            paragraphs = soup.find_all("p")
            long_paragraphs = [p.get_text(strip=True) for p in paragraphs if len(p.get_text(strip=True)) > 80]
            if long_paragraphs:
                details["description"] = " ".join(long_paragraphs[:10])
                details["description_extraction_method"] = ExtractionMethod.PARAGRAPHS.value
                details["description_confidence"] = ExtractionConfidenceCalculator.score_description(
                    details["description"], ExtractionMethod.PARAGRAPHS, len(html)
                )

        # Strategy 3: article / main / section tags
        if not details["description"]:
            main_content = (
                soup.find("article")
                or soup.find("main")
                or soup.find("section")
                or soup.find("div", class_="container")
            )
            if main_content:
                for script in main_content(["script", "style"]):
                    script.decompose()
                text = main_content.get_text(strip=True)
                if len(text) > 100:
                    details["description"] = text[:5000]
                    details["description_extraction_method"] = ExtractionMethod.ARTICLE_TAG.value
                    details["description_confidence"] = ExtractionConfidenceCalculator.score_description(
                        details["description"], ExtractionMethod.ARTICLE_TAG, len(html)
                    )

        # Extract skills — try structured HTML section first, then keyword fallback
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

        # Fallback: keyword scan of the job description
        if not details.get("skills") and details.get("description"):
            found = sorted({m.lower() for m in _TECH_PATTERN.findall(details["description"])})
            if found:
                details["skills"] = found
                details["skills_confidence"] = ExtractionConfidenceCalculator.score_skills(
                    found, ExtractionMethod.FALLBACK
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
