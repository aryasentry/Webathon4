import { NextRequest, NextResponse } from 'next/server';
import { container } from '@/infrastructure/config/container';
import { AnalyzeSkillCommand } from '@/core/application/skill-analysis.ports';

// POST /api/skills/analysis
export async function POST(req: NextRequest) {
    try {
        const body = await req.json();

        // 1. Controller Only Validates Raw HTTP -> Command Mapping
        const command: AnalyzeSkillCommand = {
            userId: body.userId || 'user-123', // Demo user
            skillId: body.skillId,
            forceFreshAnalysis: body.forceFresh || false,
        };

        if (!command.skillId) {
            return NextResponse.json({ error: 'Skill ID is required' }, { status: 400 });
        }

        // 2. Call Use Case (via DI Container)
        const useCase = container.getSkillAnalysisService();
        const result = await useCase.execute(command);

        // 3. Return DTO Response
        return NextResponse.json(result);

    } catch (error: Error | any) {
        console.error('Skill Analysis Failed:', error);
        return NextResponse.json({
            error: error.message || 'Internal Server Error'
        }, { status: 500 });
    }
}
