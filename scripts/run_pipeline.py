import os, sys
sys.path.insert(0, 'c:/Users/umerj/culturix-trend-collector')

os.environ['DATABASE_URL'] = 'postgresql://postgres:gRFwohDiatCvgUOhdGmjrhaFXIFQjAYE@zephyr.proxy.rlwy.net:56811/railway'
os.environ['VOYAGE_API_KEY'] = 'pa-ij3BM22kEQub9sg6gpGezoOzsPW7vjHd0SkoMPwwRM4'
os.environ['ANTHROPIC_API_KEY'] = os.getenv('ANTHROPIC_API_KEY', '')
os.environ['DEEPSEEK_API_KEY'] = 'sk-abc2c9e628b742579926863d6dcb92da'
os.environ['QDRANT_URL'] = 'https://d897d30c-8b42-4cf6-9c44-74031d8408cf.eu-central-1-0.aws.cloud.qdrant.io'
os.environ['QDRANT_API_KEY'] = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJhY2Nlc3MiOiJtIiwic3ViamVjdCI6ImFwaS1rZXk6YjFjMTU1YjQtMTZmZi00MmE3LTk1NWUtOGI3ZjZiZDQ1OTdhIn0.IzLX0-qbgAzJiLJSpyR5jPDXfSSqXuMUqY3Zx0C9PUU'

import logging
logging.basicConfig(level=logging.INFO, format='%(name)s: %(message)s')

print('Running full pipeline...')
from app.pipeline.graph import run_pipeline
run_pipeline()
print('Done.')
