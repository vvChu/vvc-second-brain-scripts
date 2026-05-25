import sys
import time
from pathlib import Path

# Add project root to sys.path
sys.path.append(str(Path(__file__).parent.parent))

from scripts.services.wiki_health import heal_broken_links, enrich_domains
from scripts.core.log import log
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s', stream=sys.stdout)
logger = logging.getLogger("force_heal")

def main():
    logger.info("Starting background Wiki Health tasks...")
    
    # 1. Enrich Domains for all untagged concepts
    logger.info("Step 1: Enriching domains (batch_size=300)...")
    try:
        enriched_count = enrich_domains(batch_size=300)
        logger.info(f"Successfully enriched domains for {enriched_count} concepts.")
    except Exception as e:
        logger.error(f"Error enriching domains: {e}")
        
    # 2. Heal broken links (Strict LLM semantic gate)
    logger.info("Step 2: Healing broken links (Strict LLM semantic arbitration)...")
    try:
        healed_count = heal_broken_links()
        logger.info(f"Successfully healed {healed_count} broken links into stubs.")
    except Exception as e:
        logger.error(f"Error healing links: {e}")
        
    logger.info("Background Wiki Health tasks completed successfully.")

if __name__ == "__main__":
    main()
