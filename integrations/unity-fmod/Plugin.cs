using BepInEx;
using UnityEngine;

namespace UniversalDubbing.Fmod
{
    [BepInPlugin("local.universal-dubbing.fmod", "Universal Dubbing FMOD", "0.1.0")]
    public sealed class Plugin : BaseUnityPlugin
    {
        void Awake() {
            var service=new OverrideService(Logger,Config,Info.Location);
            OverrideService.BootstrapLifecycle("AWAKE enabled="+enabled+" active="+gameObject.activeInHierarchy);
            Application.quitting += OverrideService.ShutdownCurrent;
            service.Initialize();
        }
        void OnEnable() { OverrideService.BootstrapLifecycle("ENABLE"); }
        void OnDisable() { OverrideService.BootstrapLifecycle("DISABLE"); }
        // Rue Valley destroys the loader's MonoBehaviour during bootstrap.
        // The plain managed service is owned by static Harmony callbacks instead.
        void OnDestroy() { OverrideService.BootstrapLifecycle("DESTROY"); }
    }
}
