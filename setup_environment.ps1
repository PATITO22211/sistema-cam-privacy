# FastAPI Surveillance System - Environment Setup Script
# This script sets up a Python virtual environment with CUDA 11.8 support

Write-Host "🚀 FastAPI Surveillance System - Environment Setup" -ForegroundColor Green
Write-Host "=================================================" -ForegroundColor Green

# Check if Python is installed
Write-Host "🐍 Checking Python installation..." -ForegroundColor Yellow
try {
    $pythonVersion = python --version 2>&1
    Write-Host "✅ Found: $pythonVersion" -ForegroundColor Green
} catch {
    Write-Host "❌ Python not found. Please install Python 3.8+ first." -ForegroundColor Red
    exit 1
}

# Check Python version (should be 3.8+)
$version = python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
if ([float]$version -lt 3.8) {
    Write-Host "❌ Python 3.8+ required. Current version: $version" -ForegroundColor Red
    exit 1
}

# Create virtual environment
Write-Host "📦 Creating virtual environment..." -ForegroundColor Yellow
if (Test-Path "venv") {
    Write-Host "⚠️  Virtual environment already exists. Removing..." -ForegroundColor Yellow
    Remove-Item -Recurse -Force "venv"
}

python -m venv venv
if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ Failed to create virtual environment" -ForegroundColor Red
    exit 1
}

Write-Host "✅ Virtual environment created" -ForegroundColor Green

# Activate virtual environment
Write-Host "🔧 Activating virtual environment..." -ForegroundColor Yellow
& ".\venv\Scripts\Activate.ps1"

# Upgrade pip
Write-Host "📈 Upgrading pip..." -ForegroundColor Yellow
python -m pip install --upgrade pip

# Install PyTorch with CUDA 11.8 support first
Write-Host "🔥 Installing PyTorch with CUDA 11.8 support..." -ForegroundColor Yellow
pip install torch==2.1.0+cu118 torchvision==0.16.0+cu118 torchaudio==2.1.0+cu118 --index-url https://download.pytorch.org/whl/cu118

if ($LASTEXITCODE -ne 0) {
    Write-Host "⚠️  CUDA 11.8 PyTorch installation failed. Installing CPU version..." -ForegroundColor Yellow
    pip install torch==2.1.0 torchvision==0.16.0 torchaudio==2.1.0
}

# Install other requirements
Write-Host "📚 Installing other requirements..." -ForegroundColor Yellow
pip install fastapi==0.104.1
pip install uvicorn[standard]==0.24.0
pip install python-multipart==0.0.6
pip install jinja2==3.1.2
pip install opencv-python==4.8.1.78
pip install ultralytics==8.0.206
pip install numpy==1.24.3
pip install pillow==10.0.1
pip install pygame==2.5.2
pip install pydantic==2.5.0
pip install python-dotenv==1.0.0
pip install websockets==12.0
pip install aiofiles==23.2.1
pip install psutil==5.9.6
pip install requests==2.31.0

# Install development dependencies
Write-Host "🛠️  Installing development dependencies..." -ForegroundColor Yellow
pip install pytest==7.4.3
pip install pytest-asyncio==0.21.1
pip install httpx==0.25.2

# Verify CUDA availability
Write-Host "🔍 Checking CUDA availability..." -ForegroundColor Yellow
$cudaCheck = python -c "import torch; print('CUDA available:', torch.cuda.is_available()); print('CUDA version:', torch.version.cuda if torch.cuda.is_available() else 'N/A')" 2>&1
Write-Host $cudaCheck -ForegroundColor Cyan

# Create directories if they don't exist
Write-Host "📁 Creating required directories..." -ForegroundColor Yellow
$directories = @("static", "templates", "audio", "logs")
foreach ($dir in $directories) {
    if (!(Test-Path $dir)) {
        New-Item -ItemType Directory -Path $dir
        Write-Host "✅ Created directory: $dir" -ForegroundColor Green
    }
}

# Create .env file if it doesn't exist
Write-Host "⚙️  Creating environment configuration..." -ForegroundColor Yellow
if (!(Test-Path ".env")) {
    @"
# FastAPI Surveillance System Configuration
DEBUG=true
HOST=0.0.0.0
PORT=8000

# YOLO Configuration
YOLO_MODEL_PATH=yolov8n.pt

# Camera Configuration
MAX_QUEUE_SIZE=10
CONNECTION_TIMEOUT=5000
READ_TIMEOUT=5000

# Audio Configuration
AUDIO_PATH=audio
SOUND_COOLDOWN=3.0

# Session Configuration
SESSION_TIMEOUT=3600
SECRET_KEY=your-secret-key-here

# WebSocket Configuration
WS_HEARTBEAT_INTERVAL=30
"@ | Out-File -FilePath ".env" -Encoding UTF8
    Write-Host "✅ Created .env configuration file" -ForegroundColor Green
}

# Download YOLO model if it doesn't exist
Write-Host "🤖 Checking YOLO model..." -ForegroundColor Yellow
if (!(Test-Path "yolov8n.pt")) {
    Write-Host "📥 Downloading YOLOv8 model..." -ForegroundColor Yellow
    python -c "from ultralytics import YOLO; model = YOLO('yolov8n.pt')"
    Write-Host "✅ YOLO model downloaded" -ForegroundColor Green
}

Write-Host ""
Write-Host "🎉 Environment setup complete!" -ForegroundColor Green
Write-Host "=================================================" -ForegroundColor Green
Write-Host ""
Write-Host "To start the surveillance system:" -ForegroundColor Cyan
Write-Host "1. Activate the virtual environment: .\venv\Scripts\Activate.ps1" -ForegroundColor White
Write-Host "2. Run the application: python main.py" -ForegroundColor White
Write-Host ""
Write-Host "Or use: uvicorn main:app --host 0.0.0.0 --port 8000 --reload" -ForegroundColor White
Write-Host ""
Write-Host "Access the system at: http://localhost:8000" -ForegroundColor Yellow
Write-Host "Default admin login: admin / admin123" -ForegroundColor Yellow
Write-Host "Default mama login: mama / mama123" -ForegroundColor Yellow