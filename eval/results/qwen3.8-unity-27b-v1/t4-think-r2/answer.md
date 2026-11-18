```csharp
// FILE: TailAnimator_AnimationAndIkHandler.cs
using FIMSpace.FTail;
using KinematicCharacterController;
using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using Xefier.Core.UnityEvents;

public class TailAnimator_AnimationAndIkHandler : MonoBehaviour
{
    [Header("Tail Animator")]
    [SerializeField] TailAnimator2[] tailAnimators;
    [SerializeField] Transform IkTarget;
    [SerializeField] Transform entityRoot;
    [SerializeField] float defaultSeconds = 5;
    [Header("Animator")]
    [SerializeField] Animator[] animators;
    [SerializeField] string tailOutProperty = "Activated";
    [Header("Events")]
    [SerializeField] float tailStateChangeDelay = 2.5f;
    [SerializeField] UnityEvent_Bool tailStateChanged;

    float timeSinceIKPositionSet = 0;
    bool ikPositionSet = false;

    // The tails' UseIK is these two together. ikWanted is what the IK routines and SetIKActiveState ask for; the
    // camera distance (SetIKAllowedByDistance) only gates it, so it never turns on an IK that nothing asked for.
    bool ikWanted;
    bool ikAllowedByDistance = true;

    private void Awake()
    {
        // The IK target normally lives beside the entity (not under the animated tail) so it stays put in world
        // space while the entity moves. Only do that re-parenting when an entity root is actually assigned: the
        // DemonDog tentacles ship with entityRoot deliberately empty, and re-parenting their IkTarget to the actor's
        // parent leaves it behind at the spawn point, so the chains stretch across the floor toward it ("ribbon"
        // tentacles). With no root, the IkTarget keeps riding along with the tail controller as designed.
        if (entityRoot != null && IkTarget != null)
        {
            IkTarget.SetParent(entityRoot.parent);
        }

        foreach (TailAnimator2 tailAnimator in tailAnimators)
        {
            if (tailAnimator != null && IkTarget != null)
            {
                tailAnimator.IKTarget = IkTarget;
            }

            // The tails start with the IK the prefab gives them
            if (tailAnimator != null && tailAnimator.UseIK)
            {
                ikWanted = true;
            }
        }
    }

    public void SetTargetPosition(Vector3 pos)
    {
        IkTarget.position = pos;
        timeSinceIKPositionSet = 0;
        if (!ikPositionSet)
        {
            StartCoroutineIfActive(IKPositionRoutine());
        }
    }

    public void SetIKActiveState(bool active)
    {
        ikWanted = active;
        ApplyIK();
    }

    /// <summary>
    /// For a distance switch (a Distance_UnityEvents' LessThanOrEqual / GreaterThan): out of range the tails run
    /// without IK, back in range they get the IK they were asked for meanwhile. Unlike <see cref="SetIKActiveState"/>
    /// it never switches on an IK that nothing asked for, so in range the tails react exactly as without the switch:
    /// to a heard position for <see cref="defaultSeconds"/> (<see cref="SetTargetPosition"/>), then without IK.
    /// </summary>
    public void SetIKAllowedByDistance(bool allowed)
    {
        if (ikAllowedByDistance == allowed) return;
        ikAllowedByDistance = allowed;
        ApplyIK();
    }

    void ApplyIK()
    {
        bool useIK = ikWanted && ikAllowedByDistance;
        foreach (TailAnimator2 tailAnimator in tailAnimators)
        {
            if (tailAnimator != null)
            {
                tailAnimator.UseIK = useIK;
            }
        }
    }

    // This controller is inactive while the Tenant's "Tentacle Effects" option is off and while the DemonDog is outside
    // its Super form, and its callers call into it while it is inactive: the DemonDog's form switch calls SetTailsOut on
    // every spawn and every Small/Big switch, the Tenant's state machine at spawn, and the Tenant's smell listener calls
    // SetTargetPosition. StartCoroutine on an inactive (or disabled) component logs "Coroutine couldn't be started
    // because the game object 'Tail Controller' is inactive!" and runs nothing, so start it only when it can run. That
    // leaves an inactive controller exactly as before (the coroutine ran nothing there either); its other work, such as
    // setting the animator parameters, is untouched.
    void StartCoroutineIfActive(IEnumerator routine)
    {
        if (isActiveAndEnabled)
        {
            StartCoroutine(routine);
        }
    }

    public void SetIkActiveStateForSeconds(float seconds)
    {
        StopAllCoroutines();
        StartCoroutineIfActive(IkForSecondsRoutine(seconds));
    }

    IEnumerator IkForSecondsRoutine(float seconds)
    {
        SetIKActiveState(true);
        yield return new WaitForSeconds(seconds);
        SetIKActiveState(false);
    }
    public void SetTarget(Transform target)
    {
        IkTarget = target;
        SetTargetPosition(target.position);
    }

    public void SetTailsOut(bool tailOut)
    {
        foreach(Animator animator in animators)
        {
            animator.SetBool(tailOutProperty, tailOut);
            StartCoroutineIfActive(TailStateChangedEventRoutine(tailOut));
        }
    }

    IEnumerator IKPositionRoutine()
    {
        if (!ikPositionSet)
        {
            ikPositionSet = true;
            foreach (TailAnimator2 tailAnimator in tailAnimators)
            {
                tailAnimator.IKTarget = IkTarget;
            }
            SetIKActiveState(true);
            while (timeSinceIKPositionSet < defaultSeconds)
            {
                timeSinceIKPositionSet += Time.deltaTime;
                yield return null;
            }
            ikPositionSet = false;
            SetIKActiveState(false);
        }
    }

    IEnumerator TailStateChangedEventRoutine(bool value)
    {
        yield return new WaitForSeconds(tailStateChangeDelay);
        tailStateChanged.Invoke(value);
    }



}

```

- I guard all three `StartCoroutine` call sites (`IKPositionRoutine`, `IkForSecondsRoutine`, `TailStateChangedEventRoutine`) through one `StartCoroutineIfActive` helper so the change is in one place; the non-coroutine work in those methods (IK target position, `animator.SetBool`, `StopAllCoroutines`) still runs when the controller is inactive.
- `isActiveAndEnabled` checks both the inactive GameObject and a disabled component, so neither logs the error; a disabled component errors on `StartCoroutine` too, just with a different message.
- On an inactive controller nothing runs today (the coroutine starts nothing), so skipping the start is behaviour-preserving; I did not defer starting the coroutine until the controller becomes active, which the task did not ask for.

[qwen3.8-unity:27b on http://192.168.1.182:11434: 2012 prompt tokens, 4495 answer tokens, 25 tokens/s]