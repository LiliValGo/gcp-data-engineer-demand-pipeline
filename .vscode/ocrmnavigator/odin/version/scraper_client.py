from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from tenacity import retry, stop_after_attempt, wait_fixed
from config import config
from search_strategy import get_strategy_urls
import time


class GetOnBoardClient:

    def __init__(self):
        self.driver = None
        self._init_driver()

    def _init_driver(self):
        """Inicializa o reinicia el driver de Chrome"""
        if self.driver:
            try:
                self.driver.quit()
            except:
                pass
        
        options = webdriver.ChromeOptions()
        options.add_argument('--headless')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--disable-blink-features=AutomationControlled')
        options.add_argument(f'user-agent={config.user_agent}')
        
        self.driver = webdriver.Chrome(
            service=Service(ChromeDriverManager().install()),
            options=options
        )

    @retry(stop=stop_after_attempt(3), wait=wait_fixed(5))
    def search(self, search_term: str) -> str:
        """Busca empleos navegando directamente a las URLs de categoría"""
        try:
            # Obtener URLs estratégicas para este término de búsqueda
            strategy_urls = get_strategy_urls(search_term)
            
            print(f"    [1/4] Navigating to category...", end=" ", flush=True)
            # Intentar con cada URL de estrategia hasta obtener resultados
            for strategy_url in strategy_urls:
                try:
                    self.driver.get(strategy_url)
                    time.sleep(4)  # Espera para que cargue contenido dinámico
                    print("✓")
                    
                    print(f"    [2/4] Waiting for results...", end=" ", flush=True)
                    # Esperar explícitamente a que haya resultados
                    WebDriverWait(self.driver, 10).until(
                        lambda d: len(d.find_elements(By.CLASS_NAME, "gb-results-list__item")) > 0
                    )
                    print("✓")
                    
                    print(f"[3/4] Parsing HTML...", end=" ", flush=True)
                    html = self.driver.page_source
                    print("✓")
                    
                    print(f"[4/4] Filtering by keyword...", end=" ", flush=True)
                    # La filtering se hará en el parser
                    print("✓")
                    
                    return html
                except Exception as e:
                    continue
            
            # Si ninguna URL funcionó, retornar el HTML de la última
            return self.driver.page_source
        
        except Exception as e:
            print(f"\n    ✗ Error: {str(e)[:80]}")
            return self.driver.page_source

    def get_job_details(self, url: str) -> str:
        """Navega a una URL de empleo y retorna el HTML con detalles"""
        try:
            self.driver.get(url)
            
            # Esperar a que cargue algún contenido principal
            try:
                WebDriverWait(self.driver, config.timeout).until(
                    lambda d: len(d.find_elements(By.TAG_NAME, "p")) > 0
                )
            except:
                # Si no encuentra párrafos, simplemente esperamos un tiempo fijo
                time.sleep(3)
            
            return self.driver.page_source
        
        except Exception as e:
            # Si la sesión es inválida, reiniciar el driver
            if "invalid session id" in str(e).lower():
                self._init_driver()
                # Reintentar después de restart
                self.driver.get(url)
                time.sleep(3)
                return self.driver.page_source
            else:
                raise

    def close(self):
        """Cierra el navegador"""
        try:
            if self.driver:
                self.driver.quit()
        except:
            pass