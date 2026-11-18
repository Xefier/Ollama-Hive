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

    /// <summary>
    /// StartCoroutine on an inactive GameObject (the Tenant with its "Tentacle Effects" off, the DemonDog in its
    /// Small form) logs "Coroutine couldn't be started because the game object ... is inactive!" and runs nothing.
    /// The Tenant's and the DemonDog's state machines call into a controller they have switched off, so skip it as
    /// Unity already skipped the coroutine: it runs when the GameObject is active, and not otherwise. The callers'
    /// non-coroutine work (IkTarget.position, animator parameters) still happens either way, as it did before.
    /// </summary>
    void StartCoroutineWhenActive(IEnumerator routine)
    {
        if (gameObject.activeInHierarchy)
        {
            StartCoroutine(routine);
        }
    }

    public void SetTargetPosition(Vector3 pos)
    {
        IkTarget.position = pos;
        timeSinceIKPositionSet = 0;
        if (!ikPositionSet)
        {
            StartCoroutineWhenActive(IKPositionRoutine());
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

    public void SetIkActiveStateForSeconds(float seconds)
    {
        StopAllCoroutines();
        StartCoroutineWhenActive(IkForSecondsRoutine(seconds));
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
            StartCoroutineWhenActive(TailStateChangedEventRoutine(tailOut));
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
