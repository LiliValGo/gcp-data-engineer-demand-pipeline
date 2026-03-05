import time
import os
from config import config
from client import GetOnBoardClient
from parser import parse_jobs, parse_job_details
from exporter import export_jobs


def run():
    client = GetOnBoardClient()
    all_jobs = []
    seen_urls = set()  # Rastrear URLs ya procesadas

    try:
        for term in config.search_terms:
            print(f"\n{'='*60}")
            print(f"🔍 Scraping term: {term}")
            print(f"{'='*60}")

            # Buscar empleos
            html = client.search(term)
            jobs = parse_jobs(html, term)
            
            # Filtrar duplicados por URL
            unique_jobs = [job for job in jobs if job.url not in seen_urls]
            skipped = len(jobs) - len(unique_jobs)
            
            print(f"✅ Found {len(jobs)} job listings for '{term}' ({skipped} duplicates skipped)")

            # Para cada empleo, obtener detalles
            for idx, job in enumerate(unique_jobs, 1):
                print(f"  [{idx}/{len(unique_jobs)}] Fetching: {job.title[:40]:40} @ {job.company[:20]:20}...", end=" ", flush=True)
                try:
                    # Obtener HTML de la página individual
                    job_html = client.get_job_details(job.url)
                    
                    # Extraer detalles
                    details = parse_job_details(job_html)
                    job.description = details.get("description")
                    job.skills = details.get("skills")
                    job.experience_level = details.get("experience_level")
                    job.contract_type = details.get("contract_type")
                    job.job_category = details.get("job_category")
                    
                    # Verificar si la descripción se capturó
                    desc_status = "✓" if job.description and len(job.description) > 50 else "⚠"
                    print(f"{desc_status}")
                    
                    # Marcar URL como procesada
                    seen_urls.add(job.url)
                except Exception as e:
                    print(f"✗ ({str(e)[:30]})")
                    pass
                
                time.sleep(0.5)

            all_jobs.extend(unique_jobs)
            time.sleep(config.delay_between_requests)

        # Exportar resultados
        print(f"\n{'='*60}")
        print(f"💾 Exporting {len(all_jobs)} jobs to JSON...")
        output_file = export_jobs(all_jobs, role="data_engineer")
        if os.path.exists(output_file):
            file_size = os.path.getsize(output_file)
            print(f"✅ File saved successfully!")
            print(f"   Location: {os.path.abspath(output_file)}")
            print(f"   Size: {file_size:,} bytes")
        else:
            print(f"❌ File was not created!")
        
        print(f"\n🎉 Total jobs scraped: {len(all_jobs)}")
        print(f"{'='*60}\n")
    
    finally:
        client.close()


if __name__ == "__main__":
    run()