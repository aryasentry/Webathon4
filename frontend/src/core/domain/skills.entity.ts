// ⚠️ Pure Domain: NO framework imports (No Next.js, No React, No Drizzle)

export type SkillLevel = 'Beginner' | 'Intermediate' | 'Advanced' | 'Expert';

export interface Skill {
  id: string; // Unique ID (UUID)
  userId: string; // Owner
  name: string; // "Python", "React"
  level: SkillLevel;
  tags: string[]; // ["FastAPI", "Pandas"]
  description?: string; // Optional context
  createdAt: Date;
  updatedAt: Date;
  
  // 🚩 Domain Logic Helpers
  isAdvanced(): boolean; // e.g., level === 'Advanced' | 'Expert'
  hasTag(tag: string): boolean;
}

// 🏭 Domain Factory (Ensures strict creation rules)
export class SkillFactory {
  static create(props: Omit<Skill, 'id' | 'createdAt' | 'updatedAt' | 'isAdvanced' | 'hasTag'>): Skill {
    // 1. Validation Rule: Name must be at least 2 chars
    if (props.name.length < 2) {
      throw new Error("Skill name too short");
    }

    // 2. Defaulting
    const now = new Date();
    
    return {
      ...props,
      id: crypto.randomUUID(), // Use standard Web Crypto API (Node 19+) for UUIDs
      createdAt: now,
      updatedAt: now,
      
      // Methods attached directly (could be a class too, keeping it simple func/object)
      isAdvanced() {
        return this.level === 'Advanced' || this.level === 'Expert';
      },
      hasTag(tag: string) {
        return this.tags.includes(tag);
      }
    };
  }
}
