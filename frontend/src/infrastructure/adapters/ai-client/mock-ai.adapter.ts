import { AIServicePort } from '../../../../core/application/skill-analysis.ports';
import { Skill } from '../../../../core/domain/skills.entity';

// -------------------------------------------------------------
// Adapter Strategy: Mock vs HTTP
// -------------------------------------------------------------

export class MockAIService implements AIServicePort {
    async analyzeSkillContext(skill: Skill): Promise<{ insights: string; score: number; recommendations: string[] }> {
        // 💡 Dev Experience: Instant response, no API key needed
        console.log(`[AI Adapter] Analyzing skill: ${skill.name} (Offline Mode)`);

        return {
            insights: `Mock analysis for ${skill.name}. Shows strong fundamentals but lacks advanced patterns.`,
            score: 75,
            recommendations: [
                `Use ${skill.name} with GraphQL`,
                `Optimize rendering performance`,
                `Learn about Server Components`
            ]
        };
    }
}

// -------------------------------------------------------------
// Real HTTP Adapter (Use this when Python backend is ready)
// -------------------------------------------------------------
/*
export class HttpAIService implements AIServicePort {
  constructor(private baseUrl: string) {}

  async analyzeSkillContext(skill: Skill) {
    const res = await fetch(`${this.baseUrl}/analyze`, {
      method: "POST",
      body: JSON.stringify(skill),
    });
    return res.json();
  }
}
*/
