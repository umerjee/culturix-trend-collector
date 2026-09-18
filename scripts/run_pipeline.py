import os, sys
sys.path.insert(0, 'c:/Users/umerj/culturix-trend-collector')

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

import logging
logging.basicConfig(level=logging.INFO, format='%(name)s: %(message)s')

print('Running full pipeline...')
from app.pipeline.graph import run_pipeline
run_pipeline()
print('Done.')
