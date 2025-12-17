#!/bin/bash
# FastAPI Surveillance System - Environment Setup Script
# This script sets up a Python virtual environment with CUDA 11.8 support

echo "🚀 FastAPI Surveillance System - Environment Setup"
echo "================================================="

# Check if Python is installed
echo "🐍 Checking Python installation..."
if ! command -v python3 &> /dev/null; then
    echo "❌ Python3 not found. Please install Python 3.8+ first."
    exit 1
fi

PYTHON_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo "✅ Found Python $PYTHON_VERSION"

# Check Python version (should be 3.8+)
if (( $(echo "$PYTHON_VERSION < 3.8" | bc -l) )); then
    echo "❌ Python 3.8+ required. Current version: $PYTHON_VERSION"
    exit 1
fi

# Create virtual environment
echo "📦 Creating virtual environment..."
if [ -d "venv" ]; then
    echo "⚠️  Virtual environment already exists. Removing..."
    rm -rf venv
fi

python3 -m venv venv
if [ $? -ne 0 ]; then
    echo "❌ Failed to create virtual environment"
    exit 1
fi

echo "✅ Virtual environment created"

# Activate virtual environment
echo "🔧 Activating virtual environment..."
source venv/bin/activate

# Upgrade pip
echo "📈 Upgrading pip..."
python -m pip install --upgrade pip

# Install PyTorch with CUDA 11.8 support first
echo "🔥 Installing PyTorch with CUDA 11.8 support..."
pip install torch==2.1.0+cu118 torchvision==0.16.0+cu118 torchaudio==2.1.0+cu118 --index-url https://download.pytorch.org/whl/cu118

if [ $? -ne 0 ]; then
    echo "⚠️  CUDA 11.8 PyTorch installation failed. Installing CPU version..."
    pip install torch==2.1.0 torchvision==0.16.0 torchaudio==2.1.0
fi

# Install other requirements
echo "📚 Installing other requirements..."
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
echo "🛠️  Installing development dependencies..."
pip install pytest==7.4.3
pip install pytest-asyncio==0.21.1
pip install httpx==0.25.2

# Verify CUDA availability
echo "🔍 Checking CUDA availability..."
python -c "import torch; print('CUDA available:', torch.cuda.is_available()); print('CUDA version:', torch.version.cuda if torch.cuda.is_available() else 'N/A')"

# Create directories if they don't exist
echo "📁 Creating required directories..."
for dir in static templates audio logs; do
    if [ ! -d "$dir" ]; then
        mkdir -p "$dir"
        echo "✅ Created directory: $dir"
    fi
done

# Create .env file if it doesn't exist
echo "⚙️  Creating environment configuration..."
if [ ! -f ".env" ]; then
    cat > .env << EOF
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
EOF
    echo "✅ Created .env configuration file"
fi

# Download YOLO model if it doesn't exist
echo "🤖 Checking YOLO model..."
if [ ! -f "yolov8n.pt" ]; then
    echo "📥 Downloading YOLOv8 model..."
    python -c "from ultralytics import YOLO; model = YOLO('yolov8n.pt')"
    echo "✅ YOLO model downloaded"
fi

echo ""
echo "🎉 Environment setup complete!"
echo "================================================="
echo ""
echo "To start the surveillance system:"
echo "1. Activate the virtual environment: source venv/bin/activate"
echo "2. Run the application: python main.py"
echo ""
echo "Or use: uvicorn main:app --host 0.0.0.0 --port 8000 --reload"
echo ""
echo "Access the system at: http://localhost:8000"
echo "Default admin login: admin / admin123"
echo "Default mama login: mama / mama123"