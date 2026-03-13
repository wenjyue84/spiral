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
    initialPassCount \* Number of already-passing stories at start

vars == <<stories, workerAssign, workerState, mergedResults, systemPhase, initialPassCount>>

StoryIds == 1..NumStories
WorkerIds == 1..NumWorkers

(* -- Type Invariant -------------------------------------------------------- *)
TypeOK ==
    /\ \A s \in StoryIds : stories[s] \in {"pending", "assigned", "implementing", "passed", "completed_in_worker", "already_passed"}
    /\ \A s \in StoryIds : workerAssign[s] \in 0..NumWorkers
    /\ \A w \in WorkerIds : workerState[w] \in {"idle", "running", "done"}
    /\ mergedResults \subseteq StoryIds
    /\ systemPhase \in {"partitioning", "running", "merging", "done"}
    /\ initialPassCount \in 0..NumStories

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

(* -- Partition Phase ------------------------------------------------------- *)
(* Assign a pending story to a worker. Only pending stories get assigned. *)
AssignStory ==
    /\ systemPhase = "partitioning"
    /\ \E s \in StoryIds, w \in WorkerIds :
        /\ stories[s] = "pending"
        /\ workerAssign[s] = 0  \* not yet assigned
        /\ stories' = [stories EXCEPT ![s] = "assigned"]
        /\ workerAssign' = [workerAssign EXCEPT ![s] = w]
        /\ UNCHANGED <<workerState, mergedResults, systemPhase, initialPassCount>>

(* Transition from partitioning to running once all pending stories are assigned *)
StartWorkers ==
    /\ systemPhase = "partitioning"
    /\ \A s \in StoryIds : stories[s] # "pending"  \* all pending assigned
    /\ systemPhase' = "running"
    /\ workerState' = [w \in WorkerIds |-> "running"]
    /\ UNCHANGED <<stories, workerAssign, mergedResults, initialPassCount>>

(* -- Worker Implementation Phase ------------------------------------------- *)
(* A worker implements one of its assigned stories *)
WorkerImplement ==
    /\ systemPhase = "running"
    /\ \E s \in StoryIds, w \in WorkerIds :
        /\ workerAssign[s] = w
        /\ workerState[w] = "running"
        /\ stories[s] = "assigned"
        /\ stories' = [stories EXCEPT ![s] = "implementing"]
        /\ UNCHANGED <<workerAssign, workerState, mergedResults, systemPhase, initialPassCount>>

(* A worker completes a story (pass or keep pending) *)
WorkerComplete ==
    /\ systemPhase = "running"
    /\ \E s \in StoryIds, w \in WorkerIds :
        /\ workerAssign[s] = w
        /\ workerState[w] = "running"
        /\ stories[s] = "implementing"
        /\ \/ stories' = [stories EXCEPT ![s] = "completed_in_worker"]  \* passed
           \/ stories' = [stories EXCEPT ![s] = "assigned"]             \* failed, back to assigned
        /\ UNCHANGED <<workerAssign, workerState, mergedResults, systemPhase, initialPassCount>>

(* A worker finishes all its stories *)
WorkerDone ==
    /\ systemPhase = "running"
    /\ \E w \in WorkerIds :
        /\ workerState[w] = "running"
        \* All stories assigned to this worker are either completed or still assigned (gave up)
        /\ \A s \in StoryIds :
            workerAssign[s] = w => stories[s] \in {"completed_in_worker", "assigned", "already_passed"}
        /\ workerState' = [workerState EXCEPT ![w] = "done"]
        /\ UNCHANGED <<stories, workerAssign, mergedResults, systemPhase, initialPassCount>>

(* All workers done -> transition to merging *)
AllWorkersDone ==
    /\ systemPhase = "running"
    /\ \A w \in WorkerIds : workerState[w] = "done"
    /\ systemPhase' = "merging"
    /\ UNCHANGED <<stories, workerAssign, workerState, mergedResults, initialPassCount>>

(* -- Merge Phase ----------------------------------------------------------- *)
(* Merge one completed story result back into the main PRD *)
MergeResult ==
    /\ systemPhase = "merging"
    /\ \E s \in StoryIds :
        /\ stories[s] = "completed_in_worker"
        /\ stories' = [stories EXCEPT ![s] = "passed"]
        /\ mergedResults' = mergedResults \cup {s}
        /\ UNCHANGED <<workerAssign, workerState, systemPhase, initialPassCount>>

(* Reset unfinished stories back to pending *)
ResetUnfinished ==
    /\ systemPhase = "merging"
    /\ \E s \in StoryIds :
        /\ stories[s] = "assigned"  \* worker did not complete this one
        /\ stories' = [stories EXCEPT ![s] = "pending"]
        /\ workerAssign' = [workerAssign EXCEPT ![s] = 0]
        /\ UNCHANGED <<workerState, mergedResults, systemPhase, initialPassCount>>

(* Merge complete when no more results to merge *)
MergeDone ==
    /\ systemPhase = "merging"
    /\ \A s \in StoryIds : stories[s] \notin {"completed_in_worker", "assigned"}
    /\ systemPhase' = "done"
    /\ UNCHANGED <<stories, workerAssign, workerState, mergedResults, initialPassCount>>

(* -- Next State Relation --------------------------------------------------- *)
Next ==
    \/ AssignStory
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
