from bs4 import BeautifulSoup
from datetime import datetime
from typing import List
from models import Job


def parse_jobs(html: str, search_term: str) -> List[Job]:
    """Extrae lista de empleos de la página de búsqueda"""
    soup = BeautifulSoup(html, "lxml")
    jobs = []

    # Buscar en estructura: <a class="gb-results-list__item">
    job_links = soup.find_all("a", class_="gb-results-list__item")

    for link in job_links:
        try:
            # Extraer título (dentro de <h3> o <h2> con clase gb-results-list__title)
            title_tag = link.find(["h3", "h2"], class_="gb-results-list__title")
            if not title_tag:
                continue
            
            title = title_tag.find("strong").text.strip() if title_tag.find("strong") else title_tag.text.strip()

            # Extraer empresa (segunda línea, dentro de gb-results-list__info)
            info_section = link.find("div", class_="gb-results-list__info")
            company = None
            if info_section:
                # La empresa es el <strong> dentro de gb-results-list__info
                company_tag = info_section.find("strong")
                if company_tag:
                    company = company_tag.text.strip()

            # Extraer ubicación
            location_tag = link.find("span", class_="location")
            location = location_tag.text.strip() if location_tag else None

            # Extraer salario
            salary_tag = link.find(string=lambda x: x and ("USD" in str(x) or "CLP" in str(x) or "mes" in str(x)))
            salary = salary_tag.strip() if salary_tag else None

            # Extraer URL
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
                description=None,  # Se llenará después visitando la página
                search_term=search_term,
                scraped_at=datetime.utcnow()
            )

            jobs.append(job)

        except Exception as e:
            continue

    return jobs


def parse_job_details(html: str) -> dict:
    """Extrae detalles completos de una página individual de empleo"""
    soup = BeautifulSoup(html, "lxml")
    
    details = {
        "description": None,
        "requirements": None,
        "benefits": None,
        "skills": None,
        "experience_level": None,
        "contract_type": None,
        "job_category": None
    }
    
    try:
        # Estrategia 1: Buscar por clases que contienen "description", "job", "offer"
        description_section = soup.find("div", class_=lambda x: x and any(
            keyword in str(x).lower() 
            for keyword in ["description", "job-description", "offer", "content", "post-description", "job-post"]
        ))
        
        if description_section:
            description_text = description_section.get_text(strip=True)
            if len(description_text) > 50:  # Validar que tenga contenido real
                details["description"] = description_text
        
        # Estrategia 2: Si no encuentra, buscar párrafos largos
        if not details["description"]:
            paragraphs = soup.find_all("p")
            long_paragraphs = [p.get_text(strip=True) for p in paragraphs if len(p.get_text(strip=True)) > 100]
            if long_paragraphs:
                details["description"] = " ".join(long_paragraphs[:3])  # Primeros 3 párrafos largos
        
        # Estrategia 3: Buscar en article o main tag
        if not details["description"]:
            main_content = soup.find("article") or soup.find("main") or soup.find("div", class_="container")
            if main_content:
                # Extraer todo el texto excepto scripts y estilos
                for script in main_content(["script", "style"]):
                    script.decompose()
                text = main_content.get_text(strip=True)
                if len(text) > 100:
                    details["description"] = text[:2000]  # Máximo 2000 caracteres
        
        # Estrategia 4: Buscar requirements/benefits
        requirements_section = soup.find("div", class_=lambda x: x and "requirement" in str(x).lower())
        if requirements_section:
            details["requirements"] = requirements_section.get_text(strip=True)
        
        benefits_section = soup.find("div", class_=lambda x: x and any(
            keyword in str(x).lower() 
            for keyword in ["benefit", "perk", "ventaja"]
        ))
        if benefits_section:
            details["benefits"] = benefits_section.get_text(strip=True)
        
        # Extraer skills/tecnologías
        skills_section = soup.find("div", class_=lambda x: x and any(
            keyword in str(x).lower() 
            for keyword in ["skill", "technology", "tech", "tools", "herramienta"]
        ))
        if skills_section:
            skill_items = skills_section.find_all(["li", "span", "p"])
            skills = [item.get_text(strip=True) for item in skill_items if item.get_text(strip=True)]
            if skills:
                details["skills"] = skills
        
        # Extraer nivel de experiencia
        exp_keywords = ["junior", "mid", "middle", "senior", "lead", "principal", "entry", "level"]
        for keyword in exp_keywords:
            if soup.find(string=lambda x: x and keyword.lower() in str(x).lower()):
                details["experience_level"] = keyword.capitalize()
                break
        
        # Extraer tipo de contrato
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
        
        # Extraer categoría del trabajo
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
        pass
    
    return details