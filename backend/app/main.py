from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.routes import router
from app.api.images import router as images_router
from app.api.trainings import router as trainings_router
from app.api.training_runs import router as training_runs_router
from app.api.proxy import router as proxy_router
from app.api.range_mapper import router as range_mapper_router
from app.core.vm_manager import vm_manager

app = FastAPI(title="CyberRanger API")

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    # Allow all origins for local dev (no credentials).
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api")
app.include_router(images_router, prefix="/api")
app.include_router(trainings_router, prefix="/api")
app.include_router(training_runs_router, prefix="/api")
app.include_router(proxy_router, prefix="/api")
app.include_router(range_mapper_router, prefix="/api")

@app.on_event("startup")
async def startup_event():
    vm_manager.connect()

@app.on_event("shutdown")
async def shutdown_event():
    vm_manager.disconnect()

@app.get("/")
async def root():
    return {"message": "CyberRanger API is running"}
