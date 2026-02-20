// ⚠️ Pure Application Logic: NO external adapters or frameworks
// Use Dependency Injection (via constructor params)

import { SkillAnalysisUseCase, SkillRepositoryPort, AIServicePort, AnalyzeSkillCommand, AnalyzeSkillResponse } from './skill-analysis.ports';
import { Skill } from '../domain/skills.entity';

export class SkillAnalysisService implements SkillAnalysisUseCase {
    constructor(
        private readonly repo: SkillRepositoryPort,
        private readonly ai: AIServicePort
    ) { }

    async execute(command: AnalyzeSkillCommand): Promise<AnalyzeSkillResponse> {
        // 1. Validate Input (Domain Entity Level)
        const skill = await this.repo.findById(command.skillId);

        if (!skill) {
            throw new Error(`Skill ${command.skillId} not found`);
        }

        if (skill.userId !== command.userId) {
            throw new Error("Unauthorized access to skill");
        }

        // 2. Business Logic: Do we need AI analysis?
        // Maybe we cache it (Skipping implementing cache for simplicity)

        // 3. Call AI Service (Outbound Port)
        const aiResult = await this.ai.analyzeSkillContext(skill);

        // 4. Update the Skill? Maybe persist the analysis request?
        // In a real app, we'd save this analysis Result to DB now.
        // await this.repo.saveAnalysis(aiResult); 

        // 5. Construct Response for Controller
        return {
            skillId: skill.id,
            aiInsights: aiResult.insights,
            score: aiResult.score,
            recommendedPaths: aiResult.recommendations,
            timestamp: new Date()
        };
    }
}
