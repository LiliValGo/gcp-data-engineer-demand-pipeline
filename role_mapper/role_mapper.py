import yaml
import json
import logging
from typing import Optional, List, Dict, Any
from dataclasses import dataclass
from pathlib import Path
from difflib import SequenceMatcher

import google.generativeai as genai

logger = logging.getLogger(__name__)


@dataclass
class RoleInfo:
    """Information about a role"""
    role_key: str
    primary_names: List[str]
    variants: List[str]
    description: str
    category: str
    keywords: List[str]


class RoleMapper:
    """Maps job role queries to standardized roles and variants"""

    def __init__(self, config_path: str = "role_mapper/config/roles.yaml", google_api_key: Optional[str] = None):
        self.config_path = Path(config_path)
        self.roles: Dict[str, RoleInfo] = {}
        self._load_config()

        # Initialize Gemini client for AI-powered variant generation
        self.google_api_key = google_api_key
        self.gemini_model = None
        if google_api_key:
            try:
                genai.configure(api_key=google_api_key)
                self.gemini_model = genai.GenerativeModel('gemini-1.5-flash')
                logger.info("Gemini API client initialized for AI variant generation")
            except Exception as e:
                logger.warning(f"Failed to initialize Gemini client: {e} — will fall back to templates")

        # LRU cache for AI-generated role variants (max 50 roles)
        self._generated_roles_cache = {}
        self._cache_order = []
        self._cache_max_size = 50

        logger.info(f"RoleMapper initialized with {len(self.roles)} roles")

    def _load_config(self) -> None:
        """Load role configuration from YAML"""
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)
            
            for role_key, role_data in config.get('roles', {}).items():
                self.roles[role_key] = RoleInfo(
                    role_key=role_key,
                    primary_names=role_data.get('primary_names', []),
                    variants=role_data.get('variants', []),
                    description=role_data.get('description', ''),
                    category=role_data.get('category', ''),
                    keywords=role_data.get('keywords', [])
                )
            logger.debug(f"Loaded {len(self.roles)} roles from config")
        except Exception as e:
            logger.error(f"Failed to load role config: {e}")
            raise

    def find_role(self, query: str) -> Optional[RoleInfo]:
        """
        Find a role by query string.
        
        Searches through primary names, variants, and keywords.
        Returns the best matching role or None.
        """
        query_lower = query.lower().strip()

        # Exact match in primary names or variants
        for role_key, role_info in self.roles.items():
            all_names = role_info.primary_names + role_info.variants
            for name in all_names:
                if name.lower() == query_lower:
                    logger.debug(f"Found exact match: {query} -> {role_key}")
                    return role_info
        
        # Keyword match
        for role_key, role_info in self.roles.items():
            for keyword in role_info.keywords:
                if keyword.lower() in query_lower or query_lower in keyword.lower():
                    logger.debug(f"Found keyword match: {query} -> {role_key}")
                    return role_info
        
        # Fuzzy match on variants
        best_match = None
        best_score = 0.6

        for role_key, role_info in self.roles.items():
            all_names = role_info.primary_names + role_info.variants
            for name in all_names:
                ratio = SequenceMatcher(None, query_lower, name.lower()).ratio()
                if ratio > best_score:
                    best_score = ratio
                    best_match = role_info
        
        if best_match:
            logger.debug(f"Found fuzzy match: {query} -> {best_match.role_key} (score: {best_score:.2f})")
            return best_match
        
        logger.warning(f"No role found for query: {query}")
        return None

    def get_all_variants(self, role_key: str) -> Optional[List[str]]:
        """Get all variants for a role"""
        if role_key in self.roles:
            return self.roles[role_key].variants
        logger.warning(f"Role not found: {role_key}")
        return None

    def get_similarity_score(self, role1: str, role2: str) -> float:
        """Calculate similarity between two roles (0.0 to 1.0)"""
        r1 = self.find_role(role1)
        r2 = self.find_role(role2)
        
        if not r1 or not r2:
            return 0.0
        
        # Same role
        if r1.role_key == r2.role_key:
            return 1.0
        
        # Same category
        if r1.category == r2.category:
            return 0.7
        
        # Keyword overlap
        keywords1 = set(r1.keywords)
        keywords2 = set(r2.keywords)
        overlap = len(keywords1 & keywords2)
        max_keywords = max(len(keywords1), len(keywords2))
        
        if max_keywords > 0:
            return (overlap / max_keywords) * 0.5
        
        return 0.0

    def get_related_roles(self, query: str, threshold: float = 0.6) -> List[tuple]:
        """
        Find related roles to a query role.
        
        Returns:
            List of (role_key, similarity_score) tuples sorted by score desc
        """
        role = self.find_role(query)
        if not role:
            return []
        
        related = []
        for other_key, other_role in self.roles.items():
            if other_key != role.role_key:
                score = self.get_similarity_score(role.role_key, other_key)
                if score >= threshold:
                    related.append((other_key, score))
        
        related.sort(key=lambda x: x[1], reverse=True)
        return related

    def list_all_roles(self) -> List[Dict[str, Any]]:
        """Return all available roles as dictionaries"""
        return [
            {
                "role_key": role.role_key,
                "primary_names": role.primary_names,
                "variants": role.variants,
                "description": role.description,
            }
            for role in self.roles.values()
        ]

    def _get_from_cache(self, query: str) -> Optional[Dict]:
        """Retrieve a generated role from LRU cache."""
        return self._generated_roles_cache.get(query.lower().strip())

    def _add_to_cache(self, query: str, role_data: Dict) -> None:
        """Add a generated role to LRU cache, evicting oldest if needed."""
        query_key = query.lower().strip()
        if query_key in self._generated_roles_cache:
            # Move to end (most recent)
            self._cache_order.remove(query_key)
            self._cache_order.append(query_key)
        else:
            # Add new entry
            if len(self._cache_order) >= self._cache_max_size:
                # Evict oldest
                oldest = self._cache_order.pop(0)
                del self._generated_roles_cache[oldest]
            self._cache_order.append(query_key)

        self._generated_roles_cache[query_key] = role_data
        logger.debug(f"Cached generated role '{query}' (cache size: {len(self._cache_order)}/{self._cache_max_size})")

    def generate_variants_with_gemini(self, query: str) -> Optional[Dict]:
        """
        Generate role variants, description, skills, and category using Google Gemini API.

        Returns a dict with:
        {
            "role_key": str,
            "variants": List[str],
            "description": str,
            "skills": List[str],
            "category": str,
        }

        Uses LRU cache to avoid redundant Gemini API calls.
        Falls back to template-based generation if Gemini is not available.
        """
        # Check cache first
        cached = self._get_from_cache(query)
        if cached:
            logger.debug(f"Using cached variants for '{query}'")
            return cached

        # If no Gemini model, fall back to template-based generation
        if not self.gemini_model:
            logger.debug(f"Gemini not available, using template-based variants for '{query}'")
            return self._generate_variants_template_fallback(query)

        try:
            prompt = f"""You are a tech job market expert. Generate comprehensive variants for the tech role: "{query}"

Please respond with ONLY a valid JSON object (no markdown, no extra text). Use this exact format:
{{
    "role_key": "lowercase_underscore_version_of_primary_role",
    "variants": [
        "primary role in English",
        "variant 1 in English",
        "variant 2 in English",
        "rol primario en Español",
        "variante 1 en Español",
        "variante 2 en Español"
    ],
    "description": "1-2 sentence description of what this role does",
    "skills": ["skill1", "skill2", "skill3", "skill4", "skill5"],
    "category": "one of: data, analytics, engineering, backend, frontend, devops, cloud, security, architecture, ai_ml"
}}

Ensure:
- At least 4-6 variants total (EN + ES combined)
- Include common aliases and synonyms
- Include both singular and with suffixes (engineer, developer, specialist, etc)
- Skills are realistic for someone searching job listings"""

            response = self.gemini_model.generate_content(prompt)
            response_text = response.text.strip()

            # Parse JSON response
            role_data = json.loads(response_text)

            # Validate required fields
            required = {"role_key", "variants", "description", "skills", "category"}
            if not all(field in role_data for field in required):
                raise ValueError(f"Gemini response missing required fields. Got: {role_data.keys()}")

            # Cache the result
            self._add_to_cache(query, role_data)

            logger.info(f"Generated {len(role_data['variants'])} variants for '{query}' using Gemini")
            return role_data

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse Gemini response as JSON: {e}")
            return self._generate_variants_template_fallback(query)
        except Exception as e:
            logger.error(f"Gemini API error: {e}", exc_info=True)
            return self._generate_variants_template_fallback(query)

    def _generate_variants_template_fallback(self, query: str) -> Dict:
        """Fallback to simple template-based generation when Gemini is unavailable."""
        term = query.strip().lower()

        # Detect if role already has a job title suffix
        job_suffixes = {"engineer", "developer", "manager", "owner", "lead", "specialist", "analyst", "architect", "qa", "qe", "director", "coordinator", "support"}
        has_suffix = any(term.endswith(f" {suffix}") or term == suffix for suffix in job_suffixes)

        # Spanish translations for common terms
        spanish_map = {
            "engineer": "ingeniero",
            "developer": "desarrollador",
            "manager": "gerente",
            "owner": "propietario",
            "lead": "líder",
            "specialist": "especialista",
            "analyst": "analista",
            "architect": "arquitecto",
            "qa": "qa",
            "support": "soporte",
        }

        variants = [term]  # Start with original term

        if has_suffix:
            # Role already has a suffix - generate minimal variants
            # Engineer <-> Developer swap
            swapped = term.replace("engineer", "developer").replace("developer", "engineer")
            if swapped != term:
                variants.append(swapped)

            # Spanish translation for suffix
            for eng, esp in spanish_map.items():
                if f" {eng}" in term or term == eng or term.endswith(f" {eng}"):
                    spanish_variant = term.replace(eng, esp)
                    if spanish_variant != term:
                        variants.append(spanish_variant)
                    break
        else:
            # Base term without suffix - add engineer/developer variants
            variants.extend([
                f"{term} engineer",
                f"{term} developer",
                f"ingeniero {term}",
                f"desarrollador {term}",
            ])

        variants = [v.strip() for v in variants if v and v.strip()]
        variants = list(dict.fromkeys(variants))  # deduplicate

        return {
            "role_key": term.replace(" ", "_"),
            "variants": variants,
            "description": f"Professional specializing in {term}",
            "skills": [term],
            "category": "engineering",
        }

    def generate_variants_for_unknown(self, term: str) -> List[str]:
        """
        Generate EN/ES search keyword variants for a role not in the catalog.

        Extracts the base from common suffixes ("engineer", "developer") and
        builds a small set of EN + ES equivalents so the scraper has multiple
        search terms even for roles not explicitly defined in roles.yaml.

        Examples:
            "golang engineer" → ["golang engineer", "golang developer",
                                  "ingeniero golang", "desarrollador golang"]
            "ml ops"          → ["ml ops", "ml ops engineer", "ml ops developer",
                                  "ingeniero ml ops", "desarrollador ml ops"]
        """
        term = term.strip().lower()
        base = term.replace(" engineer", "").replace(" developer", "").strip()
        candidates = [
            term,
            f"{base} engineer",
            f"{base} developer",
            f"ingeniero {base}",
            f"desarrollador {base}",
        ]
        # Preserve insertion order, remove duplicates and empty strings
        seen: set = set()
        variants = []
        for v in candidates:
            if v and v not in seen:
                seen.add(v)
                variants.append(v)
        return variants
