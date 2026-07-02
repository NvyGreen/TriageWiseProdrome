from fastapi import FastAPI

app = FastAPI(title="TriageWiseProdrome")

@app.get("/")
def root():
    return {"message": "TriageWiseProdrome API is running"}