# MAYOS Coaching Context

MAYOS supports personal training and a consented coaching relationship. A person can train, coach others, or do both through one account.

## Language

**Account**:
The identity a person uses to access MAYOS. An account can have player and coach capabilities at the same time.

**Player**:
An account holder using MAYOS for their own training. A player may also be a coach.
_Avoid_: Trainee (legacy code and API term), client

**Coach**:
An account holder who provides coaching to assigned players. A coach may also be a player.

**Assignment**:
A mutually consented coaching relationship between a coach and a player. A player has at most one active assignment, and the coach can access that player's training history only while it is active.

**Invite code**:
A single-use invitation issued by a coach. The first player to redeem it may accept an assignment with that coach.

**Training program**:
The player's current structured selection of training days and exercises.

**Program provenance**:
The origin of a training program, such as automatic generation or coach authorship. It does not change when the right to edit that program changes.

**Program authority**:
The right to change a player's program structure. It remains with the player until an assigned coach publishes a program, then belongs to that coach until the assignment ends.

**Substitution request**:
A player's request for their coach to replace an exercise in a coach-controlled program. The program does not change until the coach applies a replacement.

**Unplanned exercise**:
An exercise the player performed and recorded that was not prescribed in the active program. Recording it does not change the program.

**Workout draft**:
A workout the player has recorded on their device but has not yet committed to their training history. A draft may be captured without connectivity.

**Training schedule**:
The weekdays on which a player expects to train, interpreted in the player's timezone. It is separate from the ordered training days in a program.

**Schedule pause**:
An interval during which the player's expected training days do not count as missed days.

**Missed expected day**:
A scheduled training day that no workout satisfied within its grace period. One workout can satisfy at most one expected day.

**Check-in**:
A contact recorded by the coach and visible to both coach and player, including contact outside MAYOS. It starts the interval until the next follow-up is due.
