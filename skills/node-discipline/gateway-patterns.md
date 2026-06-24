# Gateway Patterns — IF / MERGE / SET Reference

The gateway is the only place branching, merging, and data shaping lives. These are the three shapes a gateway can take.

---

## IF Gateway

Routes data down one path based on a condition. The condition is almost always a role, a status, or a feature flag.

### Pattern

```typescript
// IF gateway: route based on role
export async function getSessions(userId: string, role: 'student' | 'tutor' | 'admin') {
  if (role === 'student') {
    return sessionDAL.getByStudentId(userId);
  } else if (role === 'tutor') {
    return sessionDAL.getByTutorId(userId);
  } else {
    return sessionDAL.getAll();
  }
}
```

### When to use IF (not MERGE or SET)

| Signal | Pattern |
|--------|---------|
| Different query paths per role | IF on `role` → dispatch to different CODE nodes |
| Different output shapes per status | IF on `status` → map to different transformers |
| Feature flag gating | IF on `featureEnabled` → route A or B |
| Auth flow decision | IF on `loginMethod` → PIN vs Google OAuth |

### Common mistakes

- **IF inside a CODE node** — branching logic doesn't belong in DAL or utils
- **IF that dispatches to the same CODE node with different args** — that's a parameter, not a gateway. Only make it a gateway when the CODE node itself changes.

---

## MERGE Gateway

Combines two or more independent data sources into a single output.

### Pattern

```typescript
// MERGE gateway: combine 3 sources into one dashboard payload
export async function getTutorDashboard(tutorId: string): Promise<TutorDashboardData> {
  const [students, sessions, activities] = await Promise.all([
    userDAL.getStudentsByTutor(tutorId),      // CODE
    sessionDAL.getByTutorId(tutorId),           // CODE
    activityDAL.getByTutorId(tutorId),          // CODE
  ]);

  return { students, sessions, activities };
}
```

### When to MERGE (not IF or SET)

| Signal | Pattern |
|--------|---------|
| Dashboard needs data from 3 collections | MERGE: `Promise.all([A, B, C])` |
| Page combines user profile + settings | MERGE: `{ user, preferences }` |
| Report needs quiz scores + attendance | MERGE: join by student ID |

### Common mistakes

- **MERGE that also transforms heavily** — fine in moderation, but if the transformation logic exceeds 20 lines, extract it to a SET step or a CODE utility
- **MERGE that wraps a single CODE call** — that's a passthrough, not a merge. Remove the gateway and call the CODE node directly (or keep as a facade if you expect more sources)
- **MERGE that waits sequentially** — use `Promise.all` unless there's a real dependency between queries

### Dual-write pattern (MERGE across collections)

```typescript
// MERGE: write to two collections atomically
export async function submitAttempt(userId: string, quizId: string, answers: Answer[]) {
  const attemptRef = await quizAttemptsDAL.saveResult(userId, quizId, answers);
  await activityDAL.logActivity(userId, 'quiz_attempt', { quizId, attemptRef });
  return attemptRef;
}
```

---

## SET Gateway

Transforms or shapes data for a specific consumer. The most underrated pattern.

### Pattern

```typescript
// SET gateway: raw data → consumer-ready shape
export function buildProgressStats(attempts: QuizAttempt[]): ProgressStats {
  return {
    averageScore: attempts.reduce((sum, a) => sum + a.score, 0) / attempts.length,
    passedQuizzes: attempts.filter(a => a.score >= a.passingThreshold).length,
    totalQuizzes: attempts.length,
    lastAttemptDate: attempts.sort((a, b) => b.completedAt - a.completedAt)[0]?.completedAt,
  };
}
```

### When to SET (not IF or MERGE)

| Signal | Pattern |
|--------|---------|
| Raw API data → UI-friendly shape | SET: rename fields, compute aggregates |
| DB timestamps → formatted dates | SET: `toLocaleDateString()` |
| Multiple enums → display labels | SET: `STATUS_LABELS[status]` |
| Score → pass/fail tier | SET: `tierForScore(score)` |

### Where SET code lives

| Scope | Location |
|-------|----------|
| Transformation reused across gateways | CODE utility (`src/lib/utils/`) |
| Single-gateway transformation | Inside the gateway function |
| Heavy KPI computation (10+ derived fields) | Separate CODE utility called by the gateway |
| UI-only formatting (date, currency) | Formatter utility, not the gateway |

### Why SET matters

Without explicit SET gateways, transformation logic seeps into:
- Components (untestable without rendering)
- Hooks (re-runs on every render)
- DAL (now it's doing two jobs)

Extracting SET logic to a CODE utility or dedicated gateway step makes it testable with a single `import`.

---

## Combined Patterns (most real gateways)

A real gateway often chains patterns:

```
IF to pick the data source → MERGE the results → SET for the consumer
```

```typescript
export async function getClassReport(
  classId: string,
  role: 'tutor' | 'admin'
): Promise<ClassReport> {
  // IF: different data for tutor vs admin
  const data = role === 'tutor'
    ? await activityDAL.getByTutorClass(classId)
    : await activityDAL.getByClass(classId);

  // MERGE: join with metadata
  const [activities, learners] = await Promise.all([
    data,
    userDAL.getByClassId(classId),
  ]);

  // SET: shape for display
  return {
    learnerCount: learners.length,
    activityFeed: activities.map(a => ({
      type: a.type,
      summary: `${a.learnerName} completed ${a.activityName}`,
      timestamp: a.completedAt,
    })),
  };
}
```

## Verification

```
[ ] Does this gateway route, merge, or shape? (Pick one primary role)
[ ] Does it call CODE nodes for the actual work?
[ ] Is the branching condition (IF) explicit and obvious?
[ ] Are MERGED sources resolved in parallel (Promise.all)?
[ ] Is SET logic extractable to a utility if a second consumer appears?
```
