from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.routes import router
from app.api.images import router as images_router
from app.core.vm_manager import vm_manager

app = FastAPI(title="CyberRange API")

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    # NOTE: Browsers reject `Access-Control-Allow-Origin: *` when credentials are allowed.
    # For local dev, allow localhost/127.0.0.1 on any port (Vite, etc.).
    allow_origins=[],
    allow_origin_regex=r"^http://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api")
app.include_router(images_router, prefix="/api")

@app.on_event("startup")
async def startup_event():
    vm_manager.connect()

@app.on_event("shutdown")
async def shutdown_event():
    vm_manager.disconnect()

@app.get("/")
async def root():
    return {"message": "CyberRange API is running"}
