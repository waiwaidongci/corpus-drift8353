import os
DATABASE_URL=os.getenv('DATABASE_URL','mysql+pymysql://corpus:corpus_demo@db:3306/corpus?charset=utf8mb4')
REDIS_URL=os.getenv('REDIS_URL','redis://redis:6379/0')
JWT_SECRET=os.environ['JWT_SECRET']
SEED_DEMO=os.getenv('SEED_DEMO','true').lower()=='true'
ARTIFACT_DIR=os.getenv('ARTIFACT_DIR','/artifacts')
