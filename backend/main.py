from fastapi import FastAPI, HTTPException, Depends, File, UploadFile, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, Boolean
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from pydantic import BaseModel
from datetime import datetime
from typing import Optional, List
import os
import uuid
import shutil
from pathlib import Path

# Database setup
DATABASE_URL = "sqlite:///./cms.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# Create directories for file uploads
UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)

# Database Models
class ContentItem(Base):
    __tablename__ = "content_items"
    
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, index=True)
    content = Column(Text)
    excerpt = Column(Text)
    category = Column(String, index=True)  # 'blog', 'event', 'news'
    image_url = Column(String, nullable=True)
    author = Column(String)
    published = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    event_date = Column(DateTime, nullable=True)  # For events
    tags = Column(String, nullable=True)  # Comma-separated tags

# Create tables
Base.metadata.create_all(bind=engine)

# Pydantic models
class ContentItemCreate(BaseModel):
    title: str
    content: str
    excerpt: Optional[str] = None
    category: str  # 'blog', 'event', 'news'
    author: str
    published: bool = False
    event_date: Optional[datetime] = None
    tags: Optional[str] = None

class ContentItemUpdate(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    excerpt: Optional[str] = None
    author: Optional[str] = None
    published: Optional[bool] = None
    event_date: Optional[datetime] = None
    tags: Optional[str] = None

class ContentItemResponse(BaseModel):
    id: int
    title: str
    content: str
    excerpt: Optional[str]
    category: str
    image_url: Optional[str]
    author: str
    published: Optional[bool]
    created_at: datetime
    updated_at: datetime
    event_date: Optional[datetime]
    tags: Optional[str]
    
    class Config:
        from_attributes = True

# FastAPI app
app = FastAPI(title="CMS API", description="Content Management System for Consulting Firm")

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Add your frontend URLs
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve static files
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

# Database dependency
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Helper functions
def save_upload_file(upload_file: UploadFile) -> str:
    """Save uploaded file and return the file path"""
    file_extension = os.path.splitext(upload_file.filename)[1]
    file_name = f"{uuid.uuid4()}{file_extension}"
    file_path = UPLOAD_DIR / file_name
    
    with file_path.open("wb") as buffer:
        shutil.copyfileobj(upload_file.file, buffer)
    
    return f"/uploads/{file_name}"

# API Routes

@app.get("/")
def read_root():
    return {"message": "CMS API is running"}

@app.post("/api/upload-image")
async def upload_image(file: UploadFile = File(...)):
    """Upload an image file"""
    if not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="File must be an image")
    
    try:
        file_url = save_upload_file(file)
        return {"image_url": file_url, "filename": file.filename}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error uploading file: {str(e)}")

@app.post("/api/content", response_model=ContentItemResponse)
def create_content(
    title: str = Form(...),
    content: str = Form(...),
    category: str = Form(...),
    author: str = Form(...),
    excerpt: str = Form(None),
    published: bool = Form(False),
    event_date: str = Form(None),
    tags: str = Form(None),
    image: UploadFile = File(None),
    db: Session = Depends(get_db)
):
    """Create new content item with optional image"""
    
    # Validate category
    valid_categories = ["blogs", "events", "news"]
    if category not in valid_categories:
        raise HTTPException(status_code=400, detail=f"Category must be one of: {valid_categories}")
    
    # Handle image upload
    image_url = None
    if image and image.filename:
        if not image.content_type.startswith("image/"):
            raise HTTPException(status_code=400, detail="File must be an image")
        image_url = save_upload_file(image)
    
    # Parse event_date if provided
    parsed_event_date = None
    if event_date:
        try:
            parsed_event_date = datetime.fromisoformat(event_date.replace('Z', '+00:00'))
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid event_date format. Use ISO format.")
    
    # Create content item
    db_item = ContentItem(
        title=title,
        content=content,
        excerpt=excerpt,
        category=category,
        image_url=image_url,
        author=author,
        published=published,
        event_date=parsed_event_date,
        tags=tags
    )
    
    db.add(db_item)
    db.commit()
    db.refresh(db_item)
    
    return db_item

@app.get("/api/content", response_model=List[ContentItemResponse])
def get_content(
    category: Optional[str] = None,
    published: Optional[bool] = None,
    limit: int = 20,
    offset: int = 0,
    db: Session = Depends(get_db)
):
    """Get content items with optional filtering"""
    query = db.query(ContentItem)
    
    if category:
        query = query.filter(ContentItem.category == category)
    if published is not None:
        query = query.filter(ContentItem.published == published)
    
    query = query.order_by(ContentItem.created_at.desc())
    items = query.offset(offset).limit(limit).all()
    
    return items

@app.get("/api/content/{item_id}", response_model=ContentItemResponse)
def get_content_item(item_id: int, db: Session = Depends(get_db)):
    """Get specific content item by ID"""
    item = db.query(ContentItem).filter(ContentItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Content item not found")
    return item

@app.put("/api/content/{item_id}", response_model=ContentItemResponse)
def update_content(
    item_id: int,
    title: str = Form(None),
    content: str = Form(None),
    excerpt: str = Form(None),
    author: str = Form(None),
    published: bool = Form(None),
    event_date: str = Form(None),
    tags: str = Form(None),
    image: UploadFile = File(None),
    db: Session = Depends(get_db)
):
    """Update content item"""
    db_item = db.query(ContentItem).filter(ContentItem.id == item_id).first()
    if not db_item:
        raise HTTPException(status_code=404, detail="Content item not found")
    
    # Update fields if provided
    if title is not None:
        db_item.title = title
    if content is not None:
        db_item.content = content
    if excerpt is not None:
        db_item.excerpt = excerpt
    if author is not None:
        db_item.author = author
    if published is not None:
        db_item.published = published
    if tags is not None:
        db_item.tags = tags
    
    # Handle event_date update
    if event_date is not None:
        try:
            db_item.event_date = datetime.fromisoformat(event_date.replace('Z', '+00:00'))
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid event_date format. Use ISO format.")
    
    # Handle image update
    if image and image.filename:
        if not image.content_type.startswith("image/"):
            raise HTTPException(status_code=400, detail="File must be an image")
        
        # Delete old image if exists
        if db_item.image_url:
            old_file_path = UPLOAD_DIR / os.path.basename(db_item.image_url)
            if old_file_path.exists():
                old_file_path.unlink()
        
        db_item.image_url = save_upload_file(image)
    
    db_item.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(db_item)
    
    return db_item

@app.delete("/api/content/{item_id}")
def delete_content(item_id: int, db: Session = Depends(get_db)):
    """Delete content item"""
    db_item = db.query(ContentItem).filter(ContentItem.id == item_id).first()
    if not db_item:
        raise HTTPException(status_code=404, detail="Content item not found")
    
    # Delete associated image if exists
    if db_item.image_url:
        file_path = UPLOAD_DIR / os.path.basename(db_item.image_url)
        if file_path.exists():
            file_path.unlink()
    
    db.delete(db_item)
    db.commit()
    
    return {"message": "Content item deleted successfully"}

# Category-specific endpoints for convenience
@app.get("/api/blogs", response_model=List[ContentItemResponse])
def get_blogs(published: bool = True, limit: int = 20, offset: int = 0, db: Session = Depends(get_db)):
    """Get blog posts"""
    return get_content(category="blogs", published=published, limit=limit, offset=offset, db=db)

@app.get("/api/events", response_model=List[ContentItemResponse])
def get_events(published: bool = True, limit: int = 20, offset: int = 0, db: Session = Depends(get_db)):
    """Get events"""
    return get_content(category="events", published=published, limit=limit, offset=offset, db=db)

@app.get("/api/news", response_model=List[ContentItemResponse])
def get_news(published: bool = True, limit: int = 20, offset: int = 0, db: Session = Depends(get_db)):
    """Get news items"""
    return get_content(category="news", published=published, limit=limit, offset=offset, db=db)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
