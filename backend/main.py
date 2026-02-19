from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict
from enum import Enum
from typing import List, Optional
import random

app = FastAPI(title="SkillManager AI Microservice")

# -----------------------------------------------------------------------------
# DTOs (Data Transfer Objects) - Must match the Frontend types!
# -----------------------------------------------------------------------------

class SkillLevel(str, Enum):
    Beginner = "Beginner"
    Intermediate = "Intermediate"
    Advanced = "Advanced"
    Expert = "Expert"

class SkillDTO(BaseModel):
    id: str
    userId: str
    name: str
    level: SkillLevel
    tags: List[str]
    description: Optional[str] = None

class AnalysisResponse(BaseModel):
    skillId: str
    executionTimeMs: int
    insights: str
    score: int
    recommendations: List[str]

# -----------------------------------------------------------------------------
# AI Logic (Could call ChatGPT/Claude/Llama)
# -----------------------------------------------------------------------------

@app.post("/analyze-skill", response_model=AnalysisResponse)
async def analyze_skill(skill: SkillDTO):
    """
    Receives a raw Skill object. 
    Stateless. Does NOT check DB.
    Just returns intelligent analysis.
    """
    print(f"Received analysis request for: {skill.name}")
    
    # 1. Simulate AI Processing
    # In reality: Call OpenAI API here
    
    # Mock Logic
    knowledge_base = {
        "Python": ["AsyncIO", "Typing", "Data Classes"],
        "React": ["Server Components", "Zustand", "Performance Profiling"],
        "Docker": ["Multi-stage builds", "Docker Compose", "K8s Basics"]
    }
    
    recs = knowledge_base.get(skill.name, ["Deep Dives", "System Design", "Testing"])
    
    return {
        "skillId": skill.id,
        "executionTimeMs": random.randint(50, 200),
        "insights": f"Based on your description, your {skill.name} skills are solid.",
        "score": random.randint(60, 95),
        "recommendations": recs
    }

# Health Check
@app.get("/health")
def health_check():
    return {"status": "ok", "service": "ai-backend-v1"}
