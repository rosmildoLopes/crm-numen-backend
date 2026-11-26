import os
import tempfile
from pathlib import Path

# Isolated database; never open the user's database or .env.
TEMP=tempfile.TemporaryDirectory()
os.environ['DATABASE_URL']='sqlite:///'+str(Path(TEMP.name)/'test.db')
os.environ['AUTOMATION_ENABLED']='false'
os.environ['EMAIL_DELIVERY_ENABLED']='false'
os.environ['ADMIN_EMAIL']='admin@example.com'
os.environ['ADMIN_PASSWORD']='test-password-123'
os.environ['JWT_SECRET']='unit-test-secret-with-more-than-32-characters'

os.environ['AI_ENABLED']='false'
os.environ['OPENAI_API_KEY']=''
os.environ['OPENAI_MODEL']=''

os.environ['DEMO_MODE']='false'
