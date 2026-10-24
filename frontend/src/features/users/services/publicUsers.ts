import type { PublicUser, PublicUserDto } from '@/features/users/types'

import { resolveAvatarUrl } from '@/features/auth/services/mappers'
import { apiFetch } from '@/services/http'

/**
 * Maps a raw `UserPublicRead` payload to the {@link PublicUser} model shown on
 * the public profile page, resolving the servable avatar URL from the stored
 * photo path.
 *
 * @param dto - Raw user payload from the backend.
 * @returns The normalized public-user model.
 */
export function mapPublicUser(dto: PublicUserDto): PublicUser {
  return {
    id: dto.id,
    name: dto.name,
    username: dto.username,
    city: dto.city ?? null,
    avatarUrl: resolveAvatarUrl(dto.photo_path),
  }
}

/**
 * Fetches a user's public-facing profile for the `/user/:id` page. The route is
 * authenticated, so this uses the authenticated user endpoint (the same one
 * activity feeds use to resolve other users), which any signed-in viewer may
 * call and which returns only the public projection.
 *
 * @param userId - The profile owner's id.
 * @param signal - Optional abort signal (e.g. TanStack Query cancellation).
 * @returns The public user, or `null` when not found.
 * @throws {HttpError} When the request fails.
 */
export async function fetchPublicUser(
  userId: number,
  signal?: AbortSignal,
): Promise<PublicUser | null> {
  const dto = await apiFetch<PublicUserDto | null>(`/users/id/${userId}`, { signal })
  return dto ? mapPublicUser(dto) : null
}

/**
 * Searches active users whose username contains the given term. Any signed-in
 * user may search; the backend returns the public projection and caps the
 * result count.
 *
 * @param username - The search term.
 * @param signal - Optional abort signal for cancellation.
 * @returns The matching users, mapped to the public model.
 * @throws {HttpError} When the request fails.
 */
export async function searchPublicUsers(
  username: string,
  signal?: AbortSignal,
): Promise<PublicUser[]> {
  const dtos = await apiFetch<PublicUserDto[]>(
    `/users/username/contains/${encodeURIComponent(username)}`,
    { signal },
  )
  return dtos.map(mapPublicUser)
}
