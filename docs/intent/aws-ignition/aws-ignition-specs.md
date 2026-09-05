# AWS Ignition — EARS Specs

- [x] **IGNITE-001**: Where a `size` query parameter is provided, the ignition function shall accept only `t4g.medium` or `t3.medium` as valid values.
- [x] **IGNITE-002**: If the `size` query parameter is provided and is not one of the allowed values, then the ignition function shall return HTTP 400 naming the allowed values, and shall not call `start_instances`.
- [x] **IGNITE-003**: When no `size` query parameter is provided, the ignition function shall default to `t4g.medium`.
- [x] **IGNITE-004**: When a valid size differs from the instance's current type, the ignition function shall attempt `modify_instance_attribute` before starting the instance.
- [x] **IGNITE-005**: If the `modify_instance_attribute` call raises an exception, then the ignition function shall proceed to start the instance rather than aborting the request.
- [x] **IGNITE-006**: For any valid `size` (or none provided), the ignition function shall call `start_instances` on the configured instance.
- [x] **IGNITE-007**: For any valid request, the ignition function shall return HTTP 200 with a body describing the resize outcome and boot action.
