// Core Application Layer: Inbound (API) and Outbound (Infra) Ports

import { Skill } from '../domain/skills.entity';

// -------------------------------------------------------------
// [INBOUND PORT] DRIVING (The Controller Calls This)
// -------------------------------------------------------------
// This is the use case: "Analyze a User's Skill"
export interface AnalyzeSkillCommand {
    userId: string;
    skillId: string;
    forceFreshAnalysis: boolean; // Re-analyze even if cached
}

export interface AnalyzeSkillResponse {
    skillId: string;
    aiInsights: string; // The GPT generated content
    score: number; // 0-100
    recommendedPaths: string[]; // ["Advanced React", "Next.js Performance"]
    timestamp: Date;
}

export interface SkillAnalysisUseCase {
    execute(command: AnalyzeSkillCommand): Promise<AnalyzeSkillResponse>;
}


// -------------------------------------------------------------
// [OUTBOUND PORT] DRIVEN (Infrastructure MUST Implement This)
// -------------------------------------------------------------

// 1. Dependency on Persistence (Repository)
// Adapters: Postgres (Production), In-Memory (Test/Dev)
export interface SkillRepositoryPort {
    save(skill: Skill): Promise<void>;
    findById(id: string): Promise<Skill | null>;
    findByUserId(userId: string): Promise<Skill[]>;
}

// 2. Dependency on AI Service (Adapter)
// Adapters: Python Backend (Via HTTP), Mock AI (Tests)
export interface AIServicePort {
    analyzeSkillContext(skill: Skill): Promise<{
        insights: string;
        score: number;
        recommendations: string[];
    }>;
}
