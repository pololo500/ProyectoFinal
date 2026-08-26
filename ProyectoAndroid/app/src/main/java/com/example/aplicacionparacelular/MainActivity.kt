package com.example.aplicacionparacelular

import android.Manifest
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import android.view.Menu
import android.view.MenuItem
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import androidx.navigation.findNavController
import androidx.navigation.fragment.NavHostFragment
import androidx.navigation.ui.AppBarConfiguration
import androidx.navigation.ui.navigateUp
import androidx.navigation.ui.setupActionBarWithNavController
import androidx.navigation.ui.setupWithNavController
import androidx.appcompat.app.AppCompatActivity
import com.example.aplicacionparacelular.databinding.ActivityMainBinding
import com.example.aplicacionparacelular.network.RobotConnectionManager

class MainActivity : AppCompatActivity() {

    private lateinit var appBarConfiguration: AppBarConfiguration
    private lateinit var binding: ActivityMainBinding

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)
        setSupportActionBar(binding.appBarMain.toolbar)

        // Initialize Robot connection (auto-discovers or loads saved IP)
        RobotConnectionManager.init(this)
        requestNotificationPermission()
        com.example.aplicacionparacelular.notifications.AppNotificationHelper.ensureChannels(this)
        com.example.aplicacionparacelular.notifications.ReminderScheduler.restoreAll(this)
        com.example.aplicacionparacelular.notifications.TeoAlertPollService.start(this)

        val navHostFragment =
            (supportFragmentManager.findFragmentById(R.id.nav_host_fragment_content_main) as NavHostFragment?)!!
        val navController = navHostFragment.navController

        findViewById<com.google.android.material.floatingactionbutton.FloatingActionButton?>(R.id.fab)
            ?.visibility = android.view.View.GONE

        val topLevel = setOf(
            R.id.nav_dashboard,
            R.id.nav_routines,
            R.id.nav_stories,
            R.id.nav_medical,
        )
        val navView = findViewById<com.google.android.material.navigation.NavigationView>(R.id.nav_view)
        appBarConfiguration = if (navView != null) {
            AppBarConfiguration(topLevel, binding.drawerLayout)
        } else {
            AppBarConfiguration(topLevel)
        }
        setupActionBarWithNavController(navController, appBarConfiguration)
        navView?.setupWithNavController(navController)
        binding.appBarMain.contentMain.bottomNavView?.setupWithNavController(navController)
    }

    override fun onDestroy() {
        super.onDestroy()
        // El poll de avisos del peluche sigue en TeoAlertPollService.
    }

    override fun onCreateOptionsMenu(menu: Menu): Boolean {
        menuInflater.inflate(R.menu.overflow, menu)
        return true
    }

    override fun onOptionsItemSelected(item: MenuItem): Boolean {
        if (item.itemId == R.id.nav_config) {
            val navController = findNavController(R.id.nav_host_fragment_content_main)
            if (navController.currentDestination?.id != R.id.nav_config) {
                navController.navigate(R.id.nav_config)
            }
            return true
        }
        return super.onOptionsItemSelected(item)
    }

    override fun onSupportNavigateUp(): Boolean {
        val navController = findNavController(R.id.nav_host_fragment_content_main)
        return navController.navigateUp(appBarConfiguration) || super.onSupportNavigateUp()
    }

    private fun requestNotificationPermission() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU) return
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS)
            == PackageManager.PERMISSION_GRANTED
        ) {
            return
        }
        ActivityCompat.requestPermissions(
            this,
            arrayOf(Manifest.permission.POST_NOTIFICATIONS),
            1001,
        )
    }
}