<img src="https://bannermd.airopi.dev/banner?title=Discord%20M3U%20stream&desc=Stream%20M3U%20videos%20inside%20Discord&repo=gazes-media/anime-download-api" width="100%" alt="banner"/>

<p align="center">
  <a href="https://www.buymeacoffee.com/airopi" target="_blank">
    <img alt="Static Badge" src="https://img.shields.io/badge/Buy_me_a_coffee!-grey?style=for-the-badge&logo=buymeacoffee">
  </a>
</p>

<h1 align="center">Discord M3U stream</h1>

The goal of this project is to be able to stream a M3U files inside a Discord video player.

The current solution consist on an API, that download the episode in a tmp directory to serve it using og: metadata to make a working episode player inside Discord. This involve that we have to wait before being able to play a video. See [an eventual better solution](./FUTURE.md).

This API consist on 1 endpoint:
`https://mp4.gazes.fr/download/{anime_id}/{episode}`

It will return a link to the file when ready:
`https://mp4.gazes.fr/result/{download_id}`
And the actual file is available at:
`https://mp4.gazes.fr/video/{download_id}.mp4`

## Support, Feedback and Community

You can reach me over Discord at `@airo.pi`. Feel free to open an issue if you encounter any problem! Feel free to contribute if you see a solution.

## License

Discord M3U stream is under the MIT Licence.
