// Adapters: Easy to swap!
// For development, use this memory adapter. 
// For production, create a DrizzleSkillRepository.

// 🟥 IMPORT: Only interfaces from Core! NO DOMAIN LOGIC here.
import { SkillRepositoryPort } from '../../../../core/application/skill-analysis.ports';
import { Skill } from '../../../../core/domain/skills.entity';


export class InMemorySkillRepository implements SkillRepositoryPort {
    private static skills: Skill[] = [
        // Pre-populate with dummy data for UI testing
        {
            id: 'skill-1',
            userId: 'user-123',
            name: 'React.js',
            level: 'Intermediate',
            tags: ['Frontend', 'Hooks', 'Next.js'],
            description: 'Used for 2 years',
            createdAt: new Date(),
            updatedAt: new Date(),
            isAdvanced: () => false,
            hasTag: (t) => t === 'Frontend'
        }
    ];

    async save(skill: Skill): Promise<void> {
        const existingIndex = InMemorySkillRepository.skills.findIndex(s => s.id === skill.id);
        if (existingIndex > -1) {
            InMemorySkillRepository.skills[existingIndex] = skill;
        } else {
            InMemorySkillRepository.skills.push(skill);
        }
        console.log(`[DB Adapter] Saved skill: ${skill.name}`);
    }

    async findById(id: string): Promise<Skill | null> {
        // Simulate DB latency
        await new Promise(resolve => setTimeout(resolve, 100));
        return InMemorySkillRepository.skills.find(s => s.id === id) || null;
    }

    async findByUserId(userId: string): Promise<Skill[]> {
        return InMemorySkillRepository.skills.filter(s => s.userId === userId);
    }
}
