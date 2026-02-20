// 🚀 Dependency Injection Factory
// -------------------------------------------------------------
// This file wires everything together. The Controller asks for a Use Case.
// The Use Case asks for Repositories.
// This container provides the implementations.

// Core
import { SkillAnalysisService } from "../../core/application/skill-analysis.service";

// Adapters
import { InMemorySkillRepository } from "../adapters/postgres/memory-skill.repository";
import { MockAIService } from "../adapters/ai-client/mock-ai.adapter";

// 💡 Singleton Pattern: We only want ONE repository instance
class DIContainer {
    private static _repo = new InMemorySkillRepository();
    // To switch to Postgres:
    // private static _repo = new PostgresSkillRepository(dbConnection);

    private static _aiService = new MockAIService();
    // To switch to Python Backend:
    // private static _aiService = new HttpAIService(process.env.AI_SERVICE_URL);

    static getSkillAnalysisService() {
        return new SkillAnalysisService(this._repo, this._aiService);
    }
}

export const container = DIContainer;
