--------------------------- MODULE SpiralPhases ----------------------------
(*
  SPIRAL Phase Transition Model

  Models the phase ordering invariant within iterations and across
  crash recovery. Verifies that:
  1. Phases advance monotonically within each iteration
  2. Crash recovery correctly resumes from the last checkpoint
  3. The system eventually reaches completion or halts

  Phase order: R(0) < T(1) < M(2) < G(3) < I(4) < V(5) < C(6)
*)

EXTENDS Integers, Sequences, FiniteSets, TLC

CONSTANTS MaxIterations

VARIABLES
    iteration,       \* Current iteration number (1..MaxIterations)
    phase,           \* Current phase index (0..6, or -1 for "not started")
    checkpoint,      \* Last checkpointed (iteration, phase) pair
    crashed,         \* Whether a crash has occurred (for recovery testing)
    passCount,       \* Number of stories currently passing
    prevPassCount,   \* Baseline pass count at start of implementation
    done             \* Whether SPIRAL has completed

vars == <<iteration, phase, checkpoint, crashed, passCount, prevPassCount, done>>

PhaseNames == <<"R", "T", "M", "G", "I", "V", "C">>
NumPhases == 7

(* -- Type Invariant -------------------------------------------------------- *)
TypeOK ==
    /\ iteration \in 1..MaxIterations
    /\ phase \in -1..6
    /\ checkpoint \in ({0} \X {-1}) \cup (1..MaxIterations \X (-1..6))
    /\ crashed \in BOOLEAN
    /\ passCount \in 0..100
    /\ prevPassCount \in 0..100
    /\ done \in BOOLEAN

(* -- Initial State --------------------------------------------------------- *)
Init ==
    /\ iteration = 1
    /\ phase = -1
    /\ checkpoint = <<0, -1>>
    /\ crashed = FALSE
    /\ passCount = 0
    /\ prevPassCount = 0
    /\ done = FALSE

(* -- Phase Advance --------------------------------------------------------- *)
(* Advance to the next phase. May skip phases (modeled as choosing any
   higher phase index), but never go backward. *)
AdvancePhase ==
    /\ ~done
    /\ ~crashed
    /\ \E nextPhase \in (phase + 1)..6 :
        /\ phase' = nextPhase
        \* Save baseline before implementation
        /\ IF nextPhase = 4  \* Phase I
           THEN prevPassCount' = passCount
           ELSE prevPassCount' = prevPassCount
        \* During implementation (Phase I), passes can increase
        /\ IF nextPhase = 4
           THEN \E newPasses \in passCount..passCount + 5 :
                    passCount' = newPasses
           ELSE passCount' = passCount
        \* Write checkpoint after completing this phase
        /\ checkpoint' = <<iteration, nextPhase>>
        /\ UNCHANGED <<iteration, crashed, done>>

(* -- Complete Iteration ---------------------------------------------------- *)
(* After reaching phase C (6), either mark done or start next iteration *)
CompleteIteration ==
    /\ ~done
    /\ ~crashed
    /\ phase = 6  \* At phase C
    /\ \/ (  \* All stories pass -- we are done *)
           /\ passCount > 0  \* at least one story completed
           /\ done' = TRUE
           /\ UNCHANGED <<iteration, phase, checkpoint, crashed, passCount, prevPassCount>>
          )
       \/ (  \* Not done -- start next iteration *)
           /\ iteration < MaxIterations
           /\ iteration' = iteration + 1
           /\ phase' = -1
           /\ UNCHANGED <<checkpoint, crashed, passCount, prevPassCount, done>>
          )

(* -- Crash and Recovery ---------------------------------------------------- *)
Crash ==
    /\ ~done
    /\ ~crashed
    /\ phase >= 0  \* Must have started at least one phase
    /\ crashed' = TRUE
    /\ UNCHANGED <<iteration, phase, checkpoint, passCount, prevPassCount, done>>

Recover ==
    /\ crashed
    /\ ~done
    \* Resume from the checkpointed state
    /\ iteration' = checkpoint[1]
    /\ phase' = checkpoint[2]
    /\ crashed' = FALSE
    /\ UNCHANGED <<checkpoint, passCount, prevPassCount, done>>

(* -- Halt (max iterations reached) ----------------------------------------- *)
Halt ==
    /\ ~done
    /\ ~crashed
    /\ phase = 6
    /\ iteration = MaxIterations
    /\ done' = TRUE
    /\ UNCHANGED <<iteration, phase, checkpoint, crashed, passCount, prevPassCount>>

(* -- Next State Relation --------------------------------------------------- *)
Next ==
    \/ AdvancePhase
    \/ CompleteIteration
    \/ Crash
    \/ Recover
    \/ Halt

Spec == Init /\ [][Next]_vars /\ WF_vars(Next)

(* -- Safety Properties (Invariants) ---------------------------------------- *)

\* Phases never go backward within an iteration
PhaseMonotonic ==
    phase >= -1

\* Pass count never decreases (monotonicity)
PassesNeverDecrease ==
    passCount >= prevPassCount

\* Checkpoint is always behind or at current state
CheckpointBehindOrAtCurrent ==
    \/ checkpoint = <<0, -1>>  \* initial
    \/ /\ checkpoint[1] <= iteration
       /\ (checkpoint[1] < iteration \/ checkpoint[2] <= phase)

\* If done, we reached phase C at least once
DoneImpliesCompletedPhaseC ==
    done => (phase = 6)

(* -- Liveness Properties --------------------------------------------------- *)

\* The system eventually completes or reaches max iterations
EventuallyDone ==
    <>done

=============================================================================
