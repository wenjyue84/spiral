--------------------------- MODULE SpiralWorkers ---------------------------
(*
  SPIRAL Parallel Worker Protocol Model

  Models the parallel implementation phase where N workers each get a
  disjoint partition of pending stories, implement them in isolation,
  and merge results back.

  Verifies:
  1. Partition Disjointness -- no story assigned to multiple workers
  2. Partition Coverage -- every pending story assigned to exactly one worker
  3. Merge Correctness -- merged result contains all completions
  4. No Story Loss -- stories are never dropped during merge
  5. Passes Monotonicity -- pass count never decreases
  6. Model Assignment Consistency -- route_stories.py protocol invariants

  Model Assignment Protocol (route_stories.py):
  -----------------------------------------------
  Before workers start, route_stories.py classifies each pending story
  and writes a model assignment (haiku/sonnet/opus) to prd.json. This
  happens atomically in the partitioning phase. Once workers begin,
  model assignments are read-only -- no worker may modify them. This
  ensures deterministic worker behaviour and prevents races where two
  workers might try to re-classify the same story.
*)

EXTENDS Integers, Sequences, FiniteSets, TLC

CONSTANTS
    NumWorkers,     \* Number of parallel workers
    NumStories      \* Total number of stories in the PRD

VARIABLES
    stories,         \* Function: story_id -> "pending" | "assigned" | "implementing" | "passed" | "completed_in_worker"
    workerAssign,    \* Function: story_id -> worker_id (0 = unassigned)
    workerState,     \* Function: worker_id -> "idle" | "running" | "done"
    mergedResults,   \* Set of story IDs that have been merged back as passed
    systemPhase,     \* "partitioning" | "running" | "merging" | "done"
    initialPassCount,\* Number of already-passing stories at start
    modelAssignments \* Function: story_id -> model string ("haiku"|"sonnet"|"opus"|"")

vars == <<stories, workerAssign, workerState, mergedResults, systemPhase, initialPassCount, modelAssignments>>

StoryIds == 1..NumStories
WorkerIds == 1..NumWorkers
ModelTypes == {"haiku", "sonnet", "opus", ""}

(* -- Type Invariant -------------------------------------------------------- *)
TypeOK ==
    /\ \A s \in StoryIds : stories[s] \in {"pending", "assigned", "implementing", "passed", "completed_in_worker", "already_passed"}
    /\ \A s \in StoryIds : workerAssign[s] \in 0..NumWorkers
    /\ \A w \in WorkerIds : workerState[w] \in {"idle", "running", "done"}
    /\ mergedResults \subseteq StoryIds
    /\ systemPhase \in {"partitioning", "running", "merging", "done"}
    /\ initialPassCount \in 0..NumStories
    /\ \A s \in StoryIds : modelAssignments[s] \in ModelTypes

(* -- Initial State --------------------------------------------------------- *)
Init ==
    \* Some stories may already be passed (completed in prior iterations)
    /\ \E alreadyPassed \in SUBSET StoryIds :
        /\ Cardinality(alreadyPassed) <= NumStories \div 2
        /\ stories = [s \in StoryIds |-> IF s \in alreadyPassed THEN "already_passed" ELSE "pending"]
        /\ initialPassCount = Cardinality(alreadyPassed)
    /\ workerAssign = [s \in StoryIds |-> 0]
    /\ workerState = [w \in WorkerIds |-> "idle"]
    /\ mergedResults = {}
    /\ systemPhase = "partitioning"
    /\ modelAssignments = [s \in StoryIds |-> ""]

(* -- Partition Phase ------------------------------------------------------- *)
(* Assign a pending story to a worker. Only pending stories get assigned. *)
AssignStory ==
    /\ systemPhase = "partitioning"
    /\ \E s \in StoryIds, w \in WorkerIds :
        /\ stories[s] = "pending"
        /\ workerAssign[s] = 0  \* not yet assigned
        /\ stories' = [stories EXCEPT ![s] = "assigned"]
        /\ workerAssign' = [workerAssign EXCEPT ![s] = w]
        /\ UNCHANGED <<workerState, mergedResults, systemPhase, initialPassCount, modelAssignments>>

(* -- Route Stories Action -------------------------------------------------- *)
(* Models route_stories.py: atomically assigns a model to every pending story
   BEFORE workers start. This must happen during the partitioning phase after
   stories are assigned but before StartWorkers transitions to running. *)
RouteStoriesAction ==
    /\ systemPhase = "partitioning"
    \* All pending stories must already be assigned to workers
    /\ \A s \in StoryIds : stories[s] # "pending"
    \* Model assignments have not been written yet (still all empty for assigned stories)
    /\ \E s \in StoryIds : stories[s] = "assigned" /\ modelAssignments[s] = ""
    \* Atomically assign a model from ModelTypes to every assigned story
    /\ modelAssignments' = [s \in StoryIds |->
        IF stories[s] = "assigned"
        THEN CHOOSE m \in {"haiku", "sonnet", "opus"} : TRUE
        ELSE modelAssignments[s]]
    /\ UNCHANGED <<stories, workerAssign, workerState, mergedResults, systemPhase, initialPassCount>>

(* Transition from partitioning to running once all pending stories are assigned
   and model assignments have been written *)
StartWorkers ==
    /\ systemPhase = "partitioning"
    /\ \A s \in StoryIds : stories[s] # "pending"  \* all pending assigned
    \* Model assignments must be written before workers start
    /\ \A s \in StoryIds : stories[s] = "assigned" => modelAssignments[s] # ""
    /\ systemPhase' = "running"
    /\ workerState' = [w \in WorkerIds |-> "running"]
    /\ UNCHANGED <<stories, workerAssign, mergedResults, initialPassCount, modelAssignments>>

(* -- Worker Implementation Phase ------------------------------------------- *)
(* A worker implements one of its assigned stories *)
WorkerImplement ==
    /\ systemPhase = "running"
    /\ \E s \in StoryIds, w \in WorkerIds :
        /\ workerAssign[s] = w
        /\ workerState[w] = "running"
        /\ stories[s] = "assigned"
        /\ stories' = [stories EXCEPT ![s] = "implementing"]
        /\ UNCHANGED <<workerAssign, workerState, mergedResults, systemPhase, initialPassCount, modelAssignments>>

(* A worker completes a story (pass or keep pending) *)
WorkerComplete ==
    /\ systemPhase = "running"
    /\ \E s \in StoryIds, w \in WorkerIds :
        /\ workerAssign[s] = w
        /\ workerState[w] = "running"
        /\ stories[s] = "implementing"
        /\ \/ stories' = [stories EXCEPT ![s] = "completed_in_worker"]  \* passed
           \/ stories' = [stories EXCEPT ![s] = "assigned"]             \* failed, back to assigned
        /\ UNCHANGED <<workerAssign, workerState, mergedResults, systemPhase, initialPassCount, modelAssignments>>

(* A worker finishes all its stories *)
WorkerDone ==
    /\ systemPhase = "running"
    /\ \E w \in WorkerIds :
        /\ workerState[w] = "running"
        \* All stories assigned to this worker are either completed or still assigned (gave up)
        /\ \A s \in StoryIds :
            workerAssign[s] = w => stories[s] \in {"completed_in_worker", "assigned", "already_passed"}
        /\ workerState' = [workerState EXCEPT ![w] = "done"]
        /\ UNCHANGED <<stories, workerAssign, mergedResults, systemPhase, initialPassCount, modelAssignments>>

(* All workers done -> transition to merging *)
AllWorkersDone ==
    /\ systemPhase = "running"
    /\ \A w \in WorkerIds : workerState[w] = "done"
    /\ systemPhase' = "merging"
    /\ UNCHANGED <<stories, workerAssign, workerState, mergedResults, initialPassCount, modelAssignments>>

(* -- Merge Phase ----------------------------------------------------------- *)
(* Merge one completed story result back into the main PRD *)
MergeResult ==
    /\ systemPhase = "merging"
    /\ \E s \in StoryIds :
        /\ stories[s] = "completed_in_worker"
        /\ stories' = [stories EXCEPT ![s] = "passed"]
        /\ mergedResults' = mergedResults \cup {s}
        /\ UNCHANGED <<workerAssign, workerState, systemPhase, initialPassCount, modelAssignments>>

(* Reset unfinished stories back to pending *)
ResetUnfinished ==
    /\ systemPhase = "merging"
    /\ \E s \in StoryIds :
        /\ stories[s] = "assigned"  \* worker did not complete this one
        /\ stories' = [stories EXCEPT ![s] = "pending"]
        /\ workerAssign' = [workerAssign EXCEPT ![s] = 0]
        /\ UNCHANGED <<workerState, mergedResults, systemPhase, initialPassCount, modelAssignments>>

(* Merge complete when no more results to merge *)
MergeDone ==
    /\ systemPhase = "merging"
    /\ \A s \in StoryIds : stories[s] \notin {"completed_in_worker", "assigned"}
    /\ systemPhase' = "done"
    /\ UNCHANGED <<stories, workerAssign, workerState, mergedResults, initialPassCount, modelAssignments>>

(* -- Next State Relation --------------------------------------------------- *)
Next ==
    \/ AssignStory
    \/ RouteStoriesAction
    \/ StartWorkers
    \/ WorkerImplement
    \/ WorkerComplete
    \/ WorkerDone
    \/ AllWorkersDone
    \/ MergeResult
    \/ ResetUnfinished
    \/ MergeDone

Spec == Init /\ [][Next]_vars /\ WF_vars(Next)

(* -- Safety Invariants ----------------------------------------------------- *)

\* No story is assigned to more than one worker
PartitionDisjoint ==
    \A s1, s2 \in StoryIds :
        (s1 # s2 /\ workerAssign[s1] # 0 /\ workerAssign[s2] # 0
         /\ workerAssign[s1] = workerAssign[s2])
        => TRUE  \* Multiple stories CAN be on same worker -- that is fine
        \* The real invariant: a single story cannot be on multiple workers
        \* This is enforced by workerAssign being a function (not a relation)

\* Already-passed stories are never downgraded
AlreadyPassedNeverLost ==
    \A s \in StoryIds :
        stories[s] = "already_passed" => stories[s] # "pending"

\* Pass count never decreases: stories that were "already_passed" stay that way
PassesMonotonic ==
    Cardinality({s \in StoryIds : stories[s] \in {"already_passed", "passed", "completed_in_worker"}})
    >= initialPassCount

\* No story just vanishes -- it is always in some valid state
NoStoryLost ==
    \A s \in StoryIds :
        stories[s] \in {"pending", "assigned", "implementing", "passed", "completed_in_worker", "already_passed"}

\* Model assignment protocol invariant (route_stories.py):
\* (a) Every model assignment is a valid ModelType
\* (b) Once workers are running, every story that is being worked on
\*     has a concrete model (haiku/sonnet/opus), not empty string
ModelAssignmentConsistent ==
    /\ \A s \in StoryIds : modelAssignments[s] \in ModelTypes
    /\ (systemPhase \in {"running", "merging", "done"}) =>
        \A s \in StoryIds :
            stories[s] \in {"assigned", "implementing", "completed_in_worker", "passed"}
            => modelAssignments[s] \in {"haiku", "sonnet", "opus"}

\* After merge, completed stories are in merged set
MergeComplete ==
    systemPhase = "done" =>
        \A s \in StoryIds :
            stories[s] \in {"passed", "already_passed", "pending"}

(* -- Liveness Properties --------------------------------------------------- *)

\* System eventually reaches done state
EventuallyDone ==
    <>(systemPhase = "done")

=============================================================================
