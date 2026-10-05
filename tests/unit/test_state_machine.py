"""
tests/unit/test_state_machine.py — Unit tests for Lifecycle State Machine
"""
import unittest
from domain.sessions.models import SessionStatus, ResearchSession
from domain.lifecycle.state_machine import LifecycleStateMachine, InvalidTransitionError
from domain.lifecycle.transitions import LifecycleTransitionManager


class TestStateMachine(unittest.TestCase):

    def test_allowed_transitions(self):
        self.assertTrue(LifecycleStateMachine.can_transition(SessionStatus.CREATED, SessionStatus.STARTING))
        self.assertTrue(LifecycleStateMachine.can_transition(SessionStatus.STARTING, SessionStatus.RUNNING))
        self.assertTrue(LifecycleStateMachine.can_transition(SessionStatus.RUNNING, SessionStatus.WAITING))
        self.assertTrue(LifecycleStateMachine.can_transition(SessionStatus.WAITING, SessionStatus.SUSPENDING))
        self.assertTrue(LifecycleStateMachine.can_transition(SessionStatus.SUSPENDING, SessionStatus.SUSPENDED))
        self.assertTrue(LifecycleStateMachine.can_transition(SessionStatus.SUSPENDED, SessionStatus.RESUMING))
        self.assertTrue(LifecycleStateMachine.can_transition(SessionStatus.RESUMING, SessionStatus.RUNNING))
        self.assertTrue(LifecycleStateMachine.can_transition(SessionStatus.RUNNING, SessionStatus.COMPLETED))

    def test_illegal_transitions(self):
        # Cannot jump directly from CREATED to RUNNING
        self.assertFalse(LifecycleStateMachine.can_transition(SessionStatus.CREATED, SessionStatus.RUNNING))
        # Cannot jump from SUSPENDED directly to COMPLETED without resuming
        self.assertFalse(LifecycleStateMachine.can_transition(SessionStatus.SUSPENDED, SessionStatus.COMPLETED))
        # Cannot transition from terminal COMPLETED
        self.assertFalse(LifecycleStateMachine.can_transition(SessionStatus.COMPLETED, SessionStatus.RUNNING))

    def test_transition_manager_and_audit(self):
        session = ResearchSession(
            id="test-session-1",
            objective="Verify actor persistence",
        )
        self.assertEqual(session.version, 1)
        self.assertEqual(session.status, SessionStatus.CREATED)

        # Legal transition to STARTING
        evt = LifecycleTransitionManager.transition(
            session=session,
            target_status=SessionStatus.STARTING,
            reason="Initializing sandbox",
            actor="test_runner",
        )
        self.assertEqual(session.status, SessionStatus.STARTING)
        self.assertEqual(session.version, 2)
        self.assertEqual(len(session.audit_trail), 1)
        self.assertEqual(evt.from_status, "CREATED")
        self.assertEqual(evt.to_status, "STARTING")

        # Illegal transition raises InvalidTransitionError
        with self.assertRaises(InvalidTransitionError):
            LifecycleTransitionManager.transition(
                session=session,
                target_status=SessionStatus.SUSPENDED,
                reason="Illegal jump",
            )

    def test_optimistic_locking(self):
        session = ResearchSession(
            id="test-session-2",
            objective="Concurrency test",
        )
        self.assertEqual(session.version, 1)

        # Conflict on mismatched version
        with self.assertRaises(ValueError):
            LifecycleTransitionManager.transition(
                session=session,
                target_status=SessionStatus.STARTING,
                reason="Test",
                expected_version=99,
            )


if __name__ == "__main__":
    unittest.main()
